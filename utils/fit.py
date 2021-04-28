import os
import re
import time
import pandas as pd
import numpy as np
import tensorflow as tf
from sklearn.metrics import roc_auc_score, average_precision_score
from utils.prefit import make_model, make_roberta_model
from utils.constants import SENTENCE_LENGTH, TAGS, ROBERTA_MAX_TOKS
import datetime
from utils.misc import write_pickle, sheepish_mkdir, test_nan_inf, inv_logit, write_txt


def AL_CV(index,
          batchstring,
          embeddings,
          n_dense,
          n_units,
          dropout,
          l1_l2_pen,
          use_case_weights,
          repeat,
          fold,
          tags = TAGS):
# index = 482
# batchstring = '01'
# embeddings = 'roberta'
# n_units = 22
# n_dense = 2
# dropout = .5
# l1_l2_pen = .00001
# use_case_weights = False
# repeat = 3
# fold = 9
# tags = TAGS
    #################
    outdir = f"{os.getcwd()}/output/"
    datadir = f"{os.getcwd()}/data/"
    ALdir = f"{outdir}saved_models/AL{batchstring}/"
    cv_savepath = f"{ALdir}cv_models/"
    if embeddings == "roberta":
        cv_savepath += "roberta/"
    sheepish_mkdir(cv_savepath)
    savename = f"model_pickle_cv_{index}{tags if isinstance(tags, str) else ''}.pkl" # append the aspect if singletasking
    tokname = re.sub("model_pickle", "antiClobberToken", savename)
    tokname = re.sub("pkl", "txt", tokname)
    tags = [tags] if isinstance(tags, str) else tags
    if (savename in os.listdir(cv_savepath)) or (tokname in os.listdir(cv_savepath)):
        return
    else:
        write_txt("I am a token.  Why must we anthropomorphize everything?",
                  f"{cv_savepath}{tokname}")
        config_dict = dict(batchstring=batchstring,
                           n_dense=n_dense,
                           n_units=n_units,
                           dropout=dropout,
                           l1_l2_pen=l1_l2_pen,
                           use_case_weights=use_case_weights,
                           repeat=repeat,
                           fold=fold,
                           tags=tags)
        print(f"********************\nstarting:\n***********************\n{config_dict}")
        ##################
        # load data
        df_tr = pd.read_csv(f"{ALdir}processed_data/trvadata/r{repeat}_f{fold}_tr_df.csv", index_col=0)
        df_va = pd.read_csv(f"{ALdir}processed_data/trvadata/r{repeat}_f{fold}_va_df.csv", index_col=0)
        case_weights = pd.read_csv(f"{ALdir}processed_data/caseweights/r{repeat}_f{fold}_tr_caseweights.csv",
                                   index_col=0)

        train_sent = df_tr['sentence']
        test_sent = df_va['sentence']

        str_varnames = [i for i in df_tr.columns if re.match("pca[0-9]", i)]

        ###################
        # create model and vectorizer
        mirrored_strategy = tf.distribute.MirroredStrategy()

        mmfun = make_roberta_model if embeddings == 'roberta' else make_model
        lr = 1e-5 if embeddings == 'roberta' else 1e-4
        with mirrored_strategy.scope():
            model, vectorizer = mmfun(emb_path=f"{datadir}w2v_oa_all_300d.bin",
                                           sentence_length=SENTENCE_LENGTH,
                                           meta_shape=len(str_varnames),
                                           tags=tags,
                                           train_sent=train_sent,
                                           l1_l2_pen=l1_l2_pen,
                                           n_units=n_units,
                                           n_dense=n_dense,
                                           dropout=dropout)

            earlystopping = tf.keras.callbacks.EarlyStopping(monitor='val_loss',
                                                             patience=25,
                                                             restore_best_weights=True)
            model.compile(loss='categorical_crossentropy',
                          optimizer=tf.keras.optimizers.Adam(lr))

        #####################
        # prepare data for tensorfow
        if embeddings == 'roberta':
            tok = vectorizer(train_sent.tolist())
            tr_ids, tr_atm = [], []
            for i in range(len(train_sent)):
                if len(tok['input_ids'][i])<=ROBERTA_MAX_TOKS:
                    id = tok['input_ids'][i] + ([0] * (ROBERTA_MAX_TOKS - len(tok['input_ids'][i])))
                    att = tok['attention_mask'][i] + ([0] * (ROBERTA_MAX_TOKS - len(tok['attention_mask'][i])))
                else:
                    id = tok['input_ids'][i][:ROBERTA_MAX_TOKS]
                    att = tok['attention_mask'][i][:ROBERTA_MAX_TOKS]
                assert len(id) == ROBERTA_MAX_TOKS
                assert len(att) == ROBERTA_MAX_TOKS
                tr_ids.append(id)
                tr_atm.append(att)
            tr_ids = tf.stack(tr_ids)
            tr_atm = tf.stack(tr_atm)
            assert tr_ids.shape == tr_atm.shape

            tok = vectorizer(test_sent.tolist())
            va_ids, va_atm = [], []
            for i in range(len(test_sent)):
                if len(tok['input_ids'][i])<=ROBERTA_MAX_TOKS:
                    id = tok['input_ids'][i] + ([0] * (ROBERTA_MAX_TOKS - len(tok['input_ids'][i])))
                    att = tok['attention_mask'][i] + ([0] * (ROBERTA_MAX_TOKS - len(tok['attention_mask'][i])))
                else:
                    id = tok['input_ids'][i][:ROBERTA_MAX_TOKS]
                    att = tok['attention_mask'][i][:ROBERTA_MAX_TOKS]
                va_ids.append(id)
                va_atm.append(att)
            va_ids = tf.stack(va_ids)
            va_atm = tf.stack(va_atm)
            assert va_ids.shape == va_atm.shape

        else:
            tr_text = vectorizer(np.array([[s] for s in train_sent]))
            va_text = vectorizer(np.array([[s] for s in test_sent]))
            test_nan_inf(tr_text)
            test_nan_inf(va_text)

        tr_labels = []
        va_labels = []
        for n in tags:
            tr = tf.convert_to_tensor(df_tr[[f"{n}_neg", f"{n}_neut", f"{n}_pos"]], dtype='float32')
            va = tf.convert_to_tensor(df_va[[f"{n}_neg", f"{n}_neut", f"{n}_pos"]], dtype='float32')
            tr_labels.append(tr)
            va_labels.append(va)

        tr_struc = tf.convert_to_tensor(df_tr[str_varnames], dtype='float32')
        va_struc = tf.convert_to_tensor(df_va[str_varnames], dtype='float32')

        case_weights_tensor_list = [tf.convert_to_tensor(case_weights[t + "_cw"]) for t in tags]

        test_nan_inf(tr_labels)
        test_nan_inf(va_labels)
        test_nan_inf(tr_struc)
        test_nan_inf(va_struc)
        # test for constant columns in labels
        assert all([all(tf.reduce_mean(tf.cast(i, dtype='float32'), axis=0) % 1 > 0) for i in tr_labels])
        assert all([all(tf.reduce_mean(tf.cast(i, dtype='float32'), axis=0) % 1 > 0) for i in va_labels])

        #############################
        # initialize the bias terms with the logits of the proportions
        w = model.get_weights()
        # set the bias terms to the proportions
        for i, yi in enumerate(tr_labels):
            props = inv_logit(tf.reduce_mean(yi, axis=0).numpy())
            pos = 7 - i * 2 if len(tags) == 4 else 1 # the 1 is for single-task learning
            w[-pos] = w[-pos] * 0 + props
        model.set_weights(w)

        #############################
        # fit the model

        start_time = time.time()
        xtr = [tr_ids, tr_atm, tr_struc] if embeddings == 'roberta' else [tr_text, tr_struc]
        xva = [va_ids, va_atm, va_struc] if embeddings == 'roberta' else [va_text, va_struc]

        history = model.fit(x=xtr,
                            y=tr_labels,
                            validation_data=(xva, va_labels),
                            epochs=1,
                            batch_size=32,
                            verbose=1,
                            sample_weight=case_weights_tensor_list if use_case_weights == True else None,
                            callbacks=earlystopping)
        runtime = time.time() - start_time
        ################################
        # predictions and metrics
        va_preds = model.predict(xva)

        subtags = [f"{t}_{i}" for t in tags for i in ['neg', 'neut', 'pos']]

        va_preds = tf.concat(va_preds, axis=1).numpy()
        va_y = tf.concat(va_labels, axis=1).numpy()

        event_rate = np.stack([va_y.mean(axis=0) for i in range(va_y.shape[0])])
        SSE = np.sum((va_preds - va_y) ** 2, axis=0)
        SST = np.sum((event_rate - va_y) ** 2, axis=0)
        brier_classwise = 1 - SSE / SST
        brier_aspectwise = [1 - np.mean(SSE[(i * 3):((i + 1) * 3)]) / np.mean(SST[(i * 3):((i + 1) * 3)]) for i in
                            range(len(tags))]
        brier_all = 1 - np.sum(SSE) / np.sum(SST)

        brier_classwise = {k: brier_classwise[i] for i, k in enumerate(subtags)}
        brier_aspectwise = {k: brier_aspectwise[i] for i, k in enumerate(tags)}

        auroc = [{t: roc_auc_score(va_y[:, i], va_preds[:, i])} for i, t in enumerate(subtags)]
        auprc = [{t: average_precision_score(va_y[:, i], va_preds[:, i])} for i, t in enumerate(subtags)]

        va_preds_df = pd.DataFrame(va_preds, columns=subtags)
        va_preds_df.insert(0, 'sentence_id', df_va.sentence_id)
        va_label_df = pd.DataFrame(va_y, columns=subtags)
        va_label_df.insert(0, 'sentence_id', df_va.sentence_id)
        va_eventrate_df = pd.DataFrame(event_rate, columns=subtags)
        va_eventrate_df.insert(0, 'sentence_id', df_va.sentence_id)
        # collect the output
        config_dict = dict(batchstring=batchstring,
                           n_dense=n_dense,
                           n_units=n_units,
                           dropout=dropout,
                           l1_l2_pen=l1_l2_pen,
                           use_case_weights=use_case_weights,
                           repeat=repeat,
                           fold=fold,
                           tags=tags)
        outdict = dict(config=config_dict,
                       history=history.history,
                       va_preds=va_preds_df,
                       va_label=va_label_df,
                       va_eventrate=va_eventrate_df,
                       brier_classwise=brier_classwise,
                       brier_aspectwise=brier_aspectwise,
                       brier_all=brier_all,
                       auroc=auroc,
                       auprc=auprc,
                       weights=model.get_weights(),
                       cohort=dict(tr=list(df_tr.PAT_ID.unique()),
                                   va=list(df_va.PAT_ID.unique())),
                       runtime=runtime,
                       ran_when=datetime.datetime.now(),
                       ran_on=tf.config.list_physical_devices()
                       )
        report = '*********************************************\n\n'
        report += f"Config: \n{config_dict}\n"
        report += f"Brier classwise: \n{brier_classwise}\n"
        report += f"Brier aspectwise: \n{brier_aspectwise}\n"
        report += f"Brier all: \n{brier_all}\n"
        report += f"AUROC: \n{auroc}\n"
        report += f"AUPRC: \n{auprc}\n"
        print(report)

        write_pickle(outdict, f"{cv_savepath}{savename}")
        os.remove(f"{cv_savepath}{tokname}")
        return 0


if __name__ == "__main__":
    pass
