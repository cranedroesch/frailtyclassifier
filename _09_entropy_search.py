import os
import pandas as pd

pd.options.display.max_rows = 4000
pd.options.display.max_columns = 4000
if 'crandrew' in os.getcwd():
    os.environ['KMP_DUPLICATE_LIB_OK'] = 'True'
import re
from _99_project_module import inv_logit, send_message_to_slack, write_pickle, read_pickle
from _99_project_module import write_txt
import datetime
import tensorflow as tf
import numpy as np
import matplotlib.pyplot as plt
from tensorflow.keras.layers import concatenate, \
    LeakyReLU, LSTM, Dropout, Dense, Flatten, Bidirectional
from tensorflow.keras.regularizers import l1_l2
from tensorflow.keras import Model, Input, backend
import time
from sklearn.preprocessing import StandardScaler
import copy
from configargparse import ArgParser


def sheepish_mkdir(path):
    import os
    try:
        os.mkdir(path)
    except FileExistsError:
        pass


def makemodel(window_size, n_dense, nunits,
              dropout, pen, semipar):
    if semipar is True:
        base_shape = input_dims - len(str_varnames)
        top_shape = input_dims - len(embedding_colnames)
    else:
        base_shape = input_dims
    inp = Input(shape=(window_size, base_shape))
    LSTM_layer = LSTM(nunits, return_sequences=True,
                      kernel_regularizer=l1_l2(pen))
    bid = Bidirectional(LSTM_layer)(inp)
    # dense
    for i in range(n_dense):
        d = Dense(nunits, kernel_regularizer=l1_l2(pen))(bid if i == 0 else drp)
        lru = LeakyReLU()(d)
        drp = Dropout(dropout)(lru)
    fl = Flatten()(drp)
    if semipar is True:
        p_inp = Input(shape=(top_shape))
        conc = concatenate([p_inp, fl])
    outlayers = [Dense(3, activation="softmax", name=i,
                       kernel_regularizer=l1_l2(pen))(conc if semipar is True else fl)
                 for i in out_varnames]
    if semipar is True:
        model = Model([inp, p_inp], outlayers)
    else:
        model = Model(inp, outlayers)
    return model


def draw_hps(seed):
    np.random.seed(seed)
    hps = (int(np.random.choice(list(range(4, 40)))),  # window size
           int(np.random.choice(list(range(1, 10)))),  # n dense
           int(2 ** np.random.choice(list(range(5, 11)))),  # n units
           float(np.random.uniform(low=0, high=.5)),  # dropout
           float(10 ** np.random.uniform(-8, -2)),  # l1/l2 penalty
           bool(np.random.choice(list(range(2)))))  # semipar
    model = makemodel(*hps)
    return model, hps


def tensormaker(D, notelist, cols, ws):
    # take a data frame and a list of notes and a list of columns and a window size and return an array for feeting to tensorflow
    note_arrays = [np.array(D.loc[D.note == i, cols]) for i in notelist]
    notelist = []
    for j in range(len(note_arrays)):
        lags, leads = [], []
        for i in range(int(np.ceil(ws / 2)) - 1, 0, -1):
            li = np.concatenate([np.zeros((i, note_arrays[j].shape[1])), note_arrays[j][:-i]], axis=0)
            lags.append(li)
        assert len(set([i.shape for i in lags])) == 1  # make sure they're all the same size
        for i in range(1, int(np.floor(ws / 2)) + 1, 1):
            li = np.concatenate([note_arrays[j][i:], np.zeros((i, note_arrays[j].shape[1]))], axis=0)
            leads.append(li)
        assert len(set([i.shape for i in leads])) == 1  # make sure they're all the same size
        x = np.squeeze(np.stack([lags + [note_arrays[j]] + leads]))
        notelist.append(np.swapaxes(x, 1, 0))
    return np.concatenate(notelist, axis=0)


def make_y_list(y):
    return [y[:, i * 3:(i + 1) * 3] for i in range(len(out_varnames))]


def get_entropy_stats(i, return_raw=False):
    try:
        start = time.time()
        note = pd.read_pickle(f"{outdir}embedded_notes/{i}")
        note[str_varnames + embedding_colnames] = scaler.transform(note[str_varnames + embedding_colnames])
        note['note'] = "foo"
        if best_model['hps'][-1] is False:  # corresponds with the semipar argument
            Xte = tensormaker(note, ['foo'], str_varnames + embedding_colnames, best_model['hps'][0])
        else:
            Xte_np = tensormaker(note, ['foo'], embedding_colnames, best_model['hps'][0])
            Xte_p = np.vstack([note[str_varnames] for i in ['foo']])

        pred = model.predict([Xte_np, Xte_p] if best_model['hps'][5] is True else Xte)
        hmat = np.stack([h(i) for i in pred])
        end = time.time()

        out = dict(note=i,
                   hmean=np.mean(hmat),
                   # compute average entropy, throwing out lower half
                   hmean_top_half=np.mean(hmat[hmat > np.median(hmat)]),
                   # compute average entropy, throwing out those that are below the (skewed) average
                   hmean_above_average=np.mean(hmat[hmat > np.mean(hmat)]),
                   # maximum
                   hmax=np.max(hmat),
                   # top decile average
                   hdec=np.mean(hmat[hmat > np.quantile(hmat, .9)]),
                   # the raw predictions
                   pred=pred,
                   # time
                   time=end - start
                   )
        return out
    except Exception as e:
        print(e)
        print(i)


if __name__ == '__main__':

    # #########################################
    # # set some globals
    # batchstring = "02"
    # # set the seed and define the training and test sets
    # # mainseed = 8675309
    # # mainseed= 29062020 # 29 June 2020
    # mainseed = 20200813  # 13 August 2020 batch 2
    # mainseed = 20200824  # 24 August 2020 batch 2 reboot, after fixing sortedness issue
    # initialize_inprog = True
    # ##########################################
    p = ArgParser()
    p.add("--batchstring", help="the batch number", type=str)
    p.add("--mainseed", help="path to the embeddings file", type=int)
    options = p.parse_args()
    batchstring = options.batchstring
    mainseed = options.mainseed

    datadir = f"{os.getcwd()}/data/"
    outdir = f"{os.getcwd()}/output/"
    figdir = f"{os.getcwd()}/figures/"
    logdir = f"{os.getcwd()}/logs/"
    ALdir = f"{outdir}saved_models/AL{batchstring}/"

    sheepish_mkdir(figdir)
    sheepish_mkdir(logdir)
    sheepish_mkdir(ALdir)
    sheepish_mkdir(f"{ALdir}/ospreds")

    # # this is a CLI arg.  one worker per swarm initializes the inprog  right now I'll do this manually from one of the VMs
    # if initialize_inprog == True:
    #     # Separate script to initialize the inprog
    #     os.system(f" rm -rf {ALdir}/TBD")
    #     os.mkdir(f"{ALdir}/TBD")
    #     # list of done files
    #     mods_done = [i for i in os.listdir(ALdir) if "model_batch" in i]
    #     is_done = [re.split("_|\.", i)[-2] for i in mods_done]
    #     for i in range(100):
    #         if str(i) not in is_done:
    #             pd.DataFrame({"seed": int(i)}, index=[i]).to_csv(f"{ALdir}TBD/job{i}")
    #             print(f"made TBD {i}")
    #     # now wait for a bunch of time so that the different workers don't trip over each other
    #     # naptime = np.random.choice(300)+100
    #     # print(f"sleeping for {naptime} seconds...")
    #     # time.sleep(naptime)

    # load the notes from 2018
    notes_2018 = sorted([i for i in os.listdir(outdir + "notes_labeled_embedded/") if int(i.split("_")[-2][1:]) < 13])

    # drop the notes that aren't in the concatenated notes data frame
    # some notes got labeled and embedded but were later removed from the pipeline
    # on July 14 2020, due to the inclusion of the 12-month ICD lookback
    cndf = pd.read_pickle(f"{outdir}conc_notes_df.pkl")
    cndf = cndf.loc[cndf.LATEST_TIME < "2019-01-01"]
    cndf['month'] = cndf.LATEST_TIME.dt.month + (
            cndf.LATEST_TIME.dt.year - min(cndf.LATEST_TIME.dt.year)) * 12
    uidstr = ("m" + cndf.month.astype(str) + "_" + cndf.PAT_ID + ".csv").tolist()

    notes_2018_in_cndf = [i for i in notes_2018 if "_".join(i.split("_")[-2:]) in uidstr]
    notes_excluded = [i for i in notes_2018 if "_".join(i.split("_")[-2:]) not in uidstr]
    assert len(notes_2018_in_cndf) + len(notes_excluded) == len(notes_2018)

    # write_txt(",".join(["_".join(i.split("_")[-2:]) for i in notes_excluded]), f"{outdir}cull_list_15jul.txt")

    df = pd.concat([pd.read_csv(outdir + "notes_labeled_embedded/" + i) for i in notes_2018])
    df.drop(columns='Unnamed: 0', inplace=True)

    # split into training and validation
    np.random.seed(mainseed)
    trnotes = np.random.choice(notes_2018, len(notes_2018) * 2 // 3, replace=False)
    tenotes = [i for i in notes_2018 if i not in trnotes]
    trnotes = [re.sub("enote_", "", re.sub(".csv", "", i)) for i in trnotes]
    tenotes = [re.sub("enote_", "", re.sub(".csv", "", i)) for i in tenotes]

    # define some useful constants
    str_varnames = df.loc[:, "n_encs":'MV_LANGUAGE'].columns.tolist()
    embedding_colnames = [i for i in df.columns if re.match("identity", i)]
    out_varnames = df.loc[:, "Msk_prob":'Fall_risk'].columns.tolist()
    input_dims = len(embedding_colnames) + len(str_varnames)

    # dummies for the outcomes
    y_dums = pd.concat([pd.get_dummies(df[[i]].astype(str)) for i in out_varnames], axis=1)
    df = pd.concat([y_dums, df], axis=1)

    # get a vector of non-negatives for case weights
    tr_cw = []
    for v in out_varnames:
        non_neutral = np.array(
            np.sum(y_dums[[i for i in y_dums.columns if ("_0" not in i) and (v in i)]], axis=1)).astype \
            ('float32')
        nnweight = 1 / np.mean(non_neutral[df.note.isin(trnotes)])
        caseweights = np.ones(df.shape[0])
        caseweights[non_neutral.astype(bool)] *= nnweight
        tr_caseweights = caseweights[df.note.isin(trnotes)]
        tr_cw.append(tr_caseweights)

    loss_object = tf.keras.losses.CategoricalCrossentropy(from_logits=False)

    # scaling
    scaler = StandardScaler()
    scaler.fit(df[str_varnames + embedding_colnames].loc[df.note.isin(trnotes)])
    sdf = copy.deepcopy(df)
    sdf[str_varnames + embedding_colnames] = scaler.transform(df[str_varnames + embedding_colnames])

    # # look for hpdf
    # try:
    #     hpdf = pd.read_json(f"{ALdir}hpdf.json")
    # except Exception:
    #     # initialize a df for results
    #     hpdf = pd.DataFrame(dict(idx=list(range(100)),
    #                              window_size=np.nan,
    #                              n_dense=np.nan,
    #                              n_units=np.nan,
    #                              dropout=np.nan,
    #                              l1_l2=np.nan,
    #                              semipar=np.nan,
    #                              time_to_convergence=np.nan,
    #                              best_loss=np.nan))
    #     hpdf.to_json(f"{ALdir}hpdf.json")

    # swarm strategy: I need to do jobs 0:99, in parallel, by different machines that share a network file system.
    # The different machines shouldn't duplicate one another's work.
    # 1.  Make a directory called "TBD" in the shared file system.  populate it with little dummy files "job00":"job99"
    # 2.  Each machine will do the following if there are any files left in TBD:
    # pick one job, xx
    # try:
    # delete the "jobxx" file
    # do the job
    # write the job to shared results
    # except:
    # write a job file "jobxx" in the shared directory
    # send me a slack message
    # stop doing anything until I go and fix it

    # n_remaining = len(os.listdir(f"{ALdir}/TBD/"))
    # while n_remaining > 0:
    #     hpdf = pd.read_json(f"{ALdir}hpdf.json")
    #     job = np.random.choice(os.listdir(f"{ALdir}/TBD"), 1)[0]
    #     seed = int(job[3:])
    #     try:
    #         # queue position
    #         os.remove(f"{ALdir}/TBD/{job}")
    #         seed = int(job[3:])
    #
    #         np.random.seed(mainseed + seed)
    #         mirrored_strategy = tf.distribute.MirroredStrategy()
    #
    #         with mirrored_strategy.scope():
    #             model, hps = draw_hps(seed + mainseed)
    #
    #             for i in range(1, 7):  # put the hyperparameters in the hpdf
    #                 hpdf.loc[seed, hpdf.columns[i]] = hps[i - 1]
    #
    #             # put the data in arrays for modeling, expanding out to the window size
    #             # only converting the test into tensors, to facilitate indexing
    #             if hps[-1] is False:  # corresponds with the semipar argument
    #                 Xtr = tensormaker(sdf, trnotes, str_varnames + embedding_colnames, hps[0])
    #                 Xte = tensormaker(sdf, tenotes, str_varnames + embedding_colnames, hps[0])
    #             else:
    #                 Xtr_np = tensormaker(sdf, trnotes, embedding_colnames, hps[0])
    #                 Xte_np = tensormaker(sdf, tenotes, embedding_colnames, hps[0])
    #                 Xtr_p = np.vstack([sdf.loc[sdf.note == i, str_varnames] for i in trnotes])
    #                 Xte_p = np.vstack([sdf.loc[sdf.note == i, str_varnames] for i in tenotes])
    #             ytr = make_y_list(np.vstack([sdf.loc[sdf.note == i, y_dums.columns.tolist()] for i in trnotes]))
    #             yte = make_y_list(np.vstack([sdf.loc[sdf.note == i, y_dums.columns.tolist()] for i in tenotes]))
    #
    #             print("\n\n********************************\n\n")
    #             print(hpdf.iloc[seed])
    #
    #             start_time = time.time()
    #
    #             # initialize the bias terms with the logits of the proportions
    #             w = model.get_weights()
    #             # set the bias terms to the proportions
    #             for i in range(4):
    #                 props = np.array([inv_logit(np.mean(df.loc[df.note.isin(trnotes), out_varnames[i]] == -1)),
    #                                   inv_logit(np.mean(df.loc[df.note.isin(trnotes), out_varnames[i]] == 0)),
    #                                   inv_logit(np.mean(df.loc[df.note.isin(trnotes), out_varnames[i]] == 1))])
    #                 pos = 7 - i * 2
    #                 w[-pos] = w[-pos] * 0 + props
    #             model.set_weights(w)
    #
    #             model.compile(optimizer=tf.keras.optimizers.Adam(1e-4),
    #                           loss={'Msk_prob': tf.keras.losses.CategoricalCrossentropy(from_logits=False),
    #                                 'Nutrition': tf.keras.losses.CategoricalCrossentropy(from_logits=False),
    #                                 'Resp_imp': tf.keras.losses.CategoricalCrossentropy(from_logits=False),
    #                                 'Fall_risk': tf.keras.losses.CategoricalCrossentropy(from_logits=False)})
    #
    #         earlystopping_callback = tf.keras.callbacks.EarlyStopping(monitor='val_loss',
    #                                                                   patience=20,
    #                                                                   restore_best_weights=True)
    #         log_dir = outdir + "/logs/fit/seed_" + str(seed) + "_" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    #         # sheepish_mkdir(log_dir)
    #         # pd.DataFrame({"seed": int(i)}, index=[i]).to_csv(f"{log_dir}/job{i}")
    #
    #         tensorboard_callback = tf.keras.callbacks.TensorBoard(log_dir=log_dir, histogram_freq=1)
    #
    #         model.fit([Xtr_np, Xtr_p] if hps[5] is True else Xtr, ytr,
    #                   batch_size=256,
    #                   epochs=1000,
    #                   callbacks=[earlystopping_callback, tensorboard_callback],
    #                   sample_weight=tr_cw,
    #                   verbose=1,
    #                   validation_data=([Xte_np, Xte_p], yte) if hps[5] is True else (Xte, yte))
    #         outdict = dict(weights=model.get_weights(),
    #                        hps=hps)
    #         write_pickle(outdict, f"{ALdir}/model_batch4_{seed}.pkl")
    #
    #         pred = model.predict([Xte_np, Xte_p] if hps[5] is True else Xte)
    #         # initialize the loss and the optimizer
    #         loss_object = tf.keras.losses.CategoricalCrossentropy(from_logits=False)
    #         loss = loss_object(yte, pred)
    #
    #         catprop = np.mean([np.mean(x[:, 1]) for x in pred])
    #
    #         print(f"at {datetime.datetime.now()}")
    #         print(f"test loss: {loss}")
    #         print("quantiles of the common category")
    #         for i in range(4):
    #             print(np.quantile([pred[i][:, 1]], [.1, .2, .3, .4, .5, .6, .7, .8, .9]))
    #
    #         tf.keras.backend.clear_session()
    #         hpdf.loc[seed, 'best_loss'] = float(loss)
    #         hpdf.loc[seed, 'time_to_convergence'] = time.time() - start_time
    #         hpdf.to_json(f"{ALdir}hpdf.json")
    #     except Exception as e:
    #         # put the borken job back on the shelf
    #         pd.DataFrame({"seed": seed}, index=[seed]).to_csv(f"{ALdir}TBD/job{seed}")
    #         send_message_to_slack(e)
    #         print(e)
    #         logf = open(f"{logdir}seed{seed}.log", "w")
    #         logf.write(str(e))
    #         logf.close()
    #     n_remaining = len(os.listdir(f"{ALdir}/TBD/"))

    """
    Now figure out the winner and ingest the unlabeled notes
    """

    print('starting entropy search')

    hpdf = pd.read_json(f"{ALdir}hpdf.json")
    winner = hpdf.loc[hpdf.best_loss == hpdf.best_loss.min()]

    # load it
    best_model = pd.read_pickle(f"{ALdir}model_batch4_{int(winner.idx)}.pkl")
    model = makemodel(*best_model['hps'])
    model.set_weights(best_model['weights'])

    # find all the notes to check
    notefiles = [i for i in os.listdir(f"{outdir}embedded_notes/")]
    # lose the ones that are in the trnotes:
    trstubs = ["_".join(i.split("_")[-2:]) for i in trnotes]
    testubs = ["_".join(i.split("_")[-2:]) for i in tenotes]
    notefiles = [i for i in notefiles if (i not in trstubs) and (i not in testubs) and ("DS_Store" not in i)]
    # and lose the ones that aren't 2018
    notefiles = [i for i in notefiles if int(i.split("_")[2][1:]) <= 12]
    # lose the ones that aren't in the cndf
    # the cndf was cut on July 14, 2020 to only include notes from PTs with qualifying ICD codes from the 12 months previous
    cndf = pd.read_pickle(f"{outdir}conc_notes_df.pkl")
    cndf = cndf.loc[cndf.LATEST_TIME < "2019-01-01"]
    cndf['month'] = cndf.LATEST_TIME.dt.month + (
            cndf.LATEST_TIME.dt.year - min(cndf.LATEST_TIME.dt.year)) * 12
    cndf_notes = ("embedded_note_m" + cndf.month.astype(str) + "_" + cndf.PAT_ID + ".pkl").tolist()
    notefiles = list(set(notefiles) & set(cndf_notes))


    def h(x):
        """entropy"""
        return -np.sum(x * np.log(x), axis=1)


    from pathlib import Path
    # randomly sort notefiles
    np.random.seed(int(time.time()))
    notefiles = list(np.random.choice(notefiles, len(notefiles), replace = False))

    N=0
    for i in notefiles:
        my_file = Path(f"{ALdir}ospreds/pred{i}.pkl")
        if my_file.is_file():
            r = get_entropy_stats(i)
            write_pickle(r, f"{ALdir}ospreds/pred{i}.pkl")
            r.pop("pred")
            print(r)
            print(i)
            N += 1
            print(N)


