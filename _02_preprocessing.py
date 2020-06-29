
'''
This script takes the data frame of raw notes generated by the previous script and does the following:
1.  Removes medication lists
2.  Joins multiword expressions
3.  "windows" notes:
    initilialize empty list of MRNs who won't be eligible for the next 6 months
    for each month
        define eligible notes as people who haven't had an eligible note in the last 6 months but are otherwise eligible
        add those people to the 6-month list, along with the month in which they were added
        take those notes, and concatenate them with the last 6 months of notes
        process the combined note, and output it
'''

import os
os.chdir("/Users/crandrew/projects/GW_PAIR_frailty_classifier/")
import pandas as pd
import matplotlib.pyplot as plt
from flashtext import KeywordProcessor
import pickle
import re
import multiprocessing as mp
import time
import numpy as np
from _99_project_module import write_txt

datadir = "/Users/crandrew/projects/GW_PAIR_frailty_classifier/data/"
outdir = "/Users/crandrew/projects/GW_PAIR_frailty_classifier/output/"
figdir = "/Users/crandrew/projects/GW_PAIR_frailty_classifier/figures/"

# preferences
pd.options.display.max_rows = 4000
pd.options.display.max_columns = 4000

# load the raw notes:
df = pd.read_pickle(f"{outdir}raw_notes_df.pkl")


def identify_spans(**kw):
    '''
    Function to identify sections of text (x) that begin with a start_phrase, end with a stop_phrase,
    contain a cutter_phrase, and don't contain a keeper_phrase
    Finally, it'll run the function extra_function to capture any task-specific corner cases
    '''
    # deal with the arguments
    x = kw.get('x')
    assert x is not None
    start_phrases = kw.get('start_phrases')
    assert start_phrases is not None
    stop_phrases = kw.get('stop_phrases')
    assert stop_phrases is not None
    cutter_phrases = kw.get('cutter_phrases')
    cutter_phrases = cutter_phrases if cutter_phrases is not None else ["SHIVER ME TIMBERS, HERE BE A DEFAULT ARGUMENT"]
    keeper_phrases = kw.get('keeper_phrases')
    keeper_phrases = keeper_phrases if keeper_phrases is not None else ["SHIVER ME TIMBERS, HERE BE A DEFAULT ARGUMENT"]
    extra_function = kw.get('extra_function')
    # begin processing:
    x = x.lower()
    # convert all non-breaking space to regular space
    x = re.sub("\xa0", " ", x)
    # put x back into the kw dict so that the extra functions can use them
    kw['x'] = x
    st_idx = [m.start() for m in re.finditer("|".join(start_phrases), x)]
    stop_idx = [m.start() for m in re.finditer("|".join(stop_phrases), x)]
    spans = []
    try:
        for j in range(len(st_idx)):
            startpos = st_idx[j]
            endpos = next((x for x in stop_idx if x > startpos), None)
            if endpos is not None:
                if j < (len(st_idx)-1): # if j is not the last element being iterated over:
                    if endpos < st_idx[j+1]: # if the end position is before the next start position
                        # implicity, if the above condition doesn't hold, nothing will get appended into spans
                        # and it'll go to the next j
                        span = x[startpos:endpos]
                        # things that it must have to get cut
                        if any(re.finditer("|".join(cutter_phrases), span)):
                            # thing that if it has it can't be cut
                            if not any(re.finditer("|".join(keeper_phrases), span)):
                                if extra_function is not None:
                                    startpos, endpos = extra_function(startpos, endpos, **kw)
                                spans.append((startpos, endpos))
                elif j == (len(st_idx)-1): # if it's the last start index, there better be a following stop index
                    span = x[startpos:endpos]
                    # things that it must have to get cut
                    if any(re.finditer("|".join(cutter_phrases), span)):
                        # thing that if it has it can't be cut
                        if not any(re.finditer("|".join(keeper_phrases), span)):
                            if extra_function is not None:
                                startpos, endpos = extra_function(startpos, endpos, **kw)
                            spans.append((startpos, endpos))
        return spans
    except Exception as e:
        return e


'''
Adult care management risk score
'''
def acm_efun(startpos, endpos, **kw):
    x = kw.get("x")
    stop_phrases = kw.get("stop_phrases")
    '''goal here is to remove text like "Current as_of just now"'''
    # update the endpos to reflect the end, rather than the start, of the end string
    endpos += next(re.finditer("|".join(stop_phrases), x[endpos:len(x)])).end()
    # find first newline after endpos+5.  the 5 is a random number to get past the first \n
    slashnpos = next(re.finditer("\n", x[(endpos+5):len(x)])).end()
    tailstring = x[endpos:(slashnpos-5+endpos+100)]
    # make sure that it contains "current as of", and that it isn't too long
    if ("current as of" in tailstring) and (len(tailstring)<40):
        return startpos, slashnpos-5+endpos
    else:
        return startpos, endpos

'''
CATv2 -- goal here is to end at the tail, rather than the front.  There are different formattings of the final score:
" Score 17 medium impact"
" Score < 10 low impact 10-20 medium impact 21-30 high impact >20 v high impact"
'''
def catv2_efun(startpos, endpos, **kw):
    x = kw.get("x")
    stop_phrases = kw.get("stop_phrases")
    # update the endpos to reflect the end, rather than the start, of the end string
    endpos += next(re.finditer("|".join(stop_phrases), x[endpos:len(x)])).end()
    # find next mention of the word "impact"
    try: # the word "impact" is usually there, but not always
        impactpos = next(re.finditer('impact', x[endpos:len(x)])).end()
        tailstring = x[endpos:(impactpos+endpos)]
        # make sure that it contains "current as of", and that it isn't too long
        if ("score" in tailstring) and (len(tailstring)<100):
            return startpos, impactpos+endpos
        else:
            return startpos, endpos
    except Exception:
        return startpos, endpos


'''
Geriatric wellness
Scanning notes, some of the questionnaires are drimmed
'''
def gw_efun(startpos, endpos, **kw):
    x = kw.get("x")
    stop_phrases = kw.get("stop_phrases")
    # update the endpos to reflect the end, rather than the start, of the end string
    endpos += next(re.finditer("|".join(stop_phrases), x[endpos:len(x)])).end()
    # find next mention of the word 'yes' or 'no' after suicidal ideation
    ynpos = next(re.finditer('yes|no', x[endpos:len(x)])).end()
    tailstring = x[endpos:(ynpos+endpos)]
    # make sure that it contains "current as of", and that it isn't too long
    if ("score" in tailstring) and (len(tailstring)<20):
        return startpos, ynpos+endpos
    else:
        return startpos, endpos


'''
Wrapper function to compute all of the spans
For each note, it'll make a list of dictionaries, with one dictionary for each of the types of questionnaires to be 
removed.
It'll have the form {questionnaire type:argsdict}.
It'll get fed to the identify_spans function, and the output will be a list of spans, in a dictionary keyed by
the questionnaire type
'''
def spans_wrapper(i):
    try:
        '''The argument is the index of the raw notes data frame'''
        # Adult care management risk score
        meta_dict = dict(acm = dict(x=df.NOTE_TEXT.iloc[i],
                                    start_phrases = ["adult care management risk score:"],
                                    stop_phrases = ["patients with an effective medicaid coverage get 1 point."],
                                    cutter_phrases = ["patients with diabetes get 1 point."],
                                    keeper_phrases = None,
                                    extra_function = acm_efun),
                         catv2=dict(x=df.NOTE_TEXT.iloc[i],
                                  start_phrases=["i never cough"],
                                  stop_phrases=["i have no energy at all"],
                                  cutter_phrases=["i do not sleep soundly due to my lung condition"],
                                  keeper_phrases=None,
                                  extra_function=catv2_efun),
                         gw=dict(x=df.NOTE_TEXT.iloc[i],
                                    start_phrases=["geriatrics wellness"],
                                    stop_phrases=["suicidal ideation"],
                                    cutter_phrases=["name a pencil and a watch"],
                                    keeper_phrases=None,
                                    extra_function=gw_efun),
                         meds = dict(x=df.NOTE_TEXT.iloc[i],
                                    start_phrases = ["\nmedication\n", "\nmedications\n", "\nprescriptions\n", "medication:",
                                                     "medications:", "prescriptions:",
                                                     "prescriptions on file"],
                                    stop_phrases = ["allergies\n", "allergies:", "allergy list\n", "allergy list:",
                                                    "-------", "\n\n\n\n",
                                                    "active medical_problems", "active medical problems", "patient active",
                                                    "past surgical history", "past_surgical_history",
                                                    "past medical history", "past_medical_history",
                                                    "review of symptoms", "review_of_symptoms",
                                                    "review of systems", "review_of_systems",
                                                    "family history", "family_history",
                                                    "social history", "social_history", "social hx:",
                                                    "physical exam:", "physical_examination", "physical examination",
                                                    "history of present illness",
                                                    "vital signs",
                                                    "\ni saw ", " i saw ",
                                                    "\npe:",
                                                    "current issues",
                                                    "history\n", "history:"],
                                    cutter_phrases = ["by_mouth", "by mouth"],
                                    keeper_phrases = ['assessment'])
        )
        keylist = list(meta_dict.keys())
        outdict = {}
        for k in keylist:
            outdict[k] = identify_spans(**meta_dict[k])
        return outdict
    except Exception as e:
        return e

# get the spans
pool = mp.Pool(mp.cpu_count())
spanslist = pool.map(spans_wrapper, range(df.shape[0]))
pool.close()

# check for errors
errs = [i for i in range(df.shape[0]) if isinstance(spanslist[i], Exception)]
assert len(errs) == 0



# do the cutting
def highlight_stuff_to_cut(i, do_cutting = False):
    # take the spans and turn them into a dataframe
    dfl = [] #data frame list
    for k in list(spanslist[i].keys()):
        if len(spanslist[i][k])>0:
            for j in range(len(spanslist[i][k])):
                out = dict(variety = k,
                           start = spanslist[i][k][j][0],
                           end = spanslist[i][k][j][1])
                dfl.append(out)
    x = df.NOTE_TEXT.iloc[i]
    if len(dfl)>0:
        sdf = pd.DataFrame(dfl)
        # check and make sure none of the spans overlap
        for j in range(sdf.shape[0]):
            c1 = any((sdf.start.iloc[j] > sdf.start) & (sdf.end.iloc[j] < sdf.end))
            if c1:
                print('overlapping spans!')
                print(i)
                # raise Exception
        # now hilight the note sections
        sdf = sdf.sort_values('start', ascending = False)
        for j in range(sdf.shape[0]):
            left = x[:sdf.start.iloc[j]]
            middle = x[sdf.start.iloc[j]:sdf.end.iloc[j]]
            right = x[sdf.end.iloc[j]:]
            if do_cutting is False:
                x = left +f"\n\n********** BEGIN Cutting {sdf.variety.iloc[j]} *************** \n\n" + \
                    middle + f"\n\n********** END Cutting {sdf.variety.iloc[j]} *************** \n\n" + right
            else:
                x = left + f"---{sdf.variety.iloc[j]}_was_here_but_got_cut----" + right
    return x

'''
There is one overlapping span at 98839.  It's a fairly intractible case.
'''

# get the spans
pool = mp.Pool(mp.cpu_count())
cut_notes = pool.map(highlight_stuff_to_cut, range(df.shape[0]))
pool.close()

checdf = df[['PAT_ID', 'CSN', 'NOTE_ID']]
checdf['notes'] = cut_notes
checdf['acm'] = [len(spanslist[i]['acm'])>0 for i in range(df.shape[0])]
checdf['catv2'] = [len(spanslist[i]['catv2'])>0 for i in range(df.shape[0])]
checdf['gw'] = [len(spanslist[i]['gw'])>0 for i in range(df.shape[0])]
checdf['meds'] = [len(spanslist[i]['meds'])>0 for i in range(df.shape[0])]


x = checdf.loc[checdf.acm == True].iloc[np.random.choice(checdf.acm.sum(), 10)]
for i in range(10):
    write_txt(x.notes.iloc[i], f"{outdir}structured_text_test_output/cutter_tester{x.NOTE_ID.iloc[i]}.txt")

x = checdf.loc[checdf.gw == True].iloc[np.random.choice(checdf.gw.sum(), 10)]
for i in range(10):
    write_txt(x.notes.iloc[i], f"{outdir}structured_text_test_output/cutter_tester{x.NOTE_ID.iloc[i]}.txt")

x = checdf.loc[checdf.catv2 == True].iloc[np.random.choice(checdf.catv2.sum(), 10)]
for i in range(10):
    write_txt(x.notes.iloc[i], f"{outdir}structured_text_test_output/cutter_tester{x.NOTE_ID.iloc[i]}.txt")


# now do the actual cutting
pool = mp.Pool(mp.cpu_count())
cut_notes = pool.starmap(highlight_stuff_to_cut, ((i, True) for i in range(df.shape[0])))
pool.close()

df['NOTE_TEXT'] = cut_notes
'''
initialize two empty data frames with patient ID and time columns.  
    - the first is the windower
    - the second is the running list of note files to generate
loop through months.  at each month:
    - drop people from the windower if they were added more than 6 months ago
    - add people to a temporary list if they are not in the windower and have a note that month
    - append the temporary list to the running list, and to the windower

'''
# create month since jan 2018 variable
df = df[df.ENC_DATE.dt.year>=2017]
df['month'] = df.ENC_DATE.dt.month + (df.ENC_DATE.dt.year - min(df.ENC_DATE.dt.year))*12
# create empty dfs
windower = pd.DataFrame(columns=["PAT_ID", "month"])
running_list = pd.DataFrame(columns=["PAT_ID", "month"])

months = [i for i in range(min(df['month']), max(df['month']) + 1)]

for m in months[12:]:
    windower = windower[(m - windower['month']) < 6]
    tmp = df[(df["month"] == m) & (~df['PAT_ID'].isin(windower['PAT_ID']))][
        ["PAT_ID", "month"]].drop_duplicates()
    windower = pd.concat([windower, tmp], axis=0, ignore_index=True)
    running_list = pd.concat([running_list, tmp], axis=0, ignore_index=True)

# plot notes per month
notes_by_month = running_list.month.value_counts().sort_index().reset_index(drop = True)
f = plt.figure()
axes = plt.gca()
axes.set_ylim([0, max(notes_by_month) + 100])
plt.plot(notes_by_month.index.values, notes_by_month, "o")
plt.plot(notes_by_month.index.values, notes_by_month)
plt.xlabel("Months since Jan 2018")
plt.ylabel("Number of notes")
# plt.show()
plt.figure(figsize=(8, 8))
f.savefig(f'{figdir}pat_per_month.pdf')


'''
armed with the running list of patient IDs, go through the note text, month by month, and concatenate all notes from 
that patient.  join MWEs while at it.
'''
mwe_dict = pickle.load(open("/Users/crandrew/projects/pwe/output/mwe_dict.pkl", 'rb'))
macer = KeywordProcessor()
macer.add_keywords_from_dict(mwe_dict)


def identify_mwes(s, macer):
    return macer.replace_keywords(s)


joiner = "\n--------------------------------------------------------------\n"




def proc(j):
    try:
        pi, mi = running_list.PAT_ID[j], running_list.month[j]  # the "+12 is there because the running list started in 2018"
        # slice the df
        ni = df[(df.PAT_ID == pi) &
                ((mi - df.month) < 6) &
                ((mi - df.month) >= 0)]
        ni = ni.sort_values(by=["ENC_DATE"], ascending=False)
        # process the notes
        comb_notes = [identify_mwes(i, macer) for i in ni.NOTE_TEXT]
        comb_string = ""
        for i in list(range(len(comb_notes))):
            comb_string = comb_string + joiner + str(ni.ENC_DATE.iloc[i]) + \
                          joiner + comb_notes[i]
        # lose multiple newlines
        comb_string = re.sub("\n+", "\n", comb_string)
        # count words
        wds = re.split(" |\n", comb_string)
        wds = [i.lower() for i in wds if i != ""]
        # join the diagnoses
        dxs = list(set((','.join(ni.dxs[~ni.dxs.isnull()].tolist())).split(",")))
        dxs.sort()
        comb_note_dict_i = dict(PAT_ID=ni.PAT_ID.iloc[0],
                                LATEST_TIME=ni.ENC_DATE.iloc[0],
                                CSNS=",".join(ni.CSN.astype(str).to_list()),
                                dxs = dxs,
                                n_comorb = len(dxs),
                                n_notes=ni.shape[0],
                                n_words=len(wds),
                                u_words=len(set(wds)),
                                combined_notes=comb_string)
        return comb_note_dict_i
    except Exception as e:
        return dict(which = j, error = e)


pool = mp.Pool(processes=mp.cpu_count())
start = time.time()
dictlist = pool.map(proc, range(running_list.shape[0]), chunksize=1)
print(time.time() - start)
pool.close()

errs = [i for i in dictlist if "error" in i.keys()]
assert len(errs) == 0

ds = dictlist
d = {}
for k in dictlist[1].keys(): # dict 1 is arbitrary -- it's just pulling the keys
    d[k] = tuple(d[k] for d in ds)
conc_notes_df = pd.DataFrame(d)

# looks for words in the text
low_prob_words = ['gym', 'exercise', 'breathing', 'appetite', 'eating', 'getting around', 'functional status',
                  'PO intake', 'getting around', 'walking', 'running', 'independent']
high_prob_words = ['PO intake', 'weight loss', 'appetite', 'frail', 'frailty', 'weakness', 'feels weak', 'unsteady',
                   'recent fall', 'getting around', 'severe dyspnea', 'functional impairment', 'difficulty walking',
                   'difficulty breathing', 'getting in the way', 'exercise', 'Breathless', 'short of breath',
                   'wheezing', 'delirium', 'dementia', 'incontinence', 'do not resuscitate', 'walker', 'wheelchair',
                   'malnutrition', 'boost']
low_prob_words = [identify_mwes(i, macer) for i in low_prob_words]
high_prob_words = [identify_mwes(i, macer) for i in high_prob_words]

low_prob_regex = '|'.join(low_prob_words)
high_prob_regex = '|'.join(high_prob_words)
# append the hp and lp columns
lp = conc_notes_df.combined_notes.str.contains(low_prob_regex)
hp = conc_notes_df.combined_notes.str.contains(high_prob_regex)
conc_notes_df['highprob'] = hp.values
conc_notes_df['lowprob'] = lp.values



conc_notes_df.to_pickle(f'{outdir}conc_notes_df.pkl')
conc_notes_df = pd.read_pickle(f'{outdir}conc_notes_df.pkl')

conc_notes_df['month'] = conc_notes_df.LATEST_TIME.dt.month + (
        conc_notes_df.LATEST_TIME.dt.year - min(conc_notes_df.LATEST_TIME.dt.year)) * 12
months = list(set(conc_notes_df.month))
months.sort()

def plotfun(var, yaxt, q=False):
    f = plt.figure()
    axes = plt.gca()
    if q:
        qvec = [np.quantile(conc_notes_df[var][conc_notes_df.month == i], [.25, .5, .75]).reshape(1, 3) for i in months]
        qmat = np.concatenate(qvec, axis=0)
        axes.set_ylim([0, np.max(qmat)])
        plt.plot(months, qmat[:, 1], "C1", label="median")
        plt.plot(months, qmat[:, 0], "C2", label="first quartile")
        plt.plot(months, qmat[:, 2], "C2", label="third quartile")
    else:
        sdvec = [np.std(conc_notes_df[var][conc_notes_df.month == i]) for i in months]
        muvec = [np.mean(conc_notes_df[var][conc_notes_df.month == i]) for i in months]
        axes.set_ylim([0, max(np.array(muvec) + np.array(sdvec))])
        plt.plot(months, muvec, "C1", label="mean")
        plt.plot(months, np.array(muvec) + np.array(sdvec), "C2", label="+/- 1 sd")
        plt.plot(months, np.array(muvec) - np.array(sdvec), "C2")
    plt.xlabel("Months since Jan 2018")
    plt.ylabel(yaxt)
    axes.legend()
    # plt.show()
    plt.figure(figsize=(8, 8))
    f.savefig(f'{figdir}{var}.pdf')


plotfun("n_notes", "Number of notes per combined note")
plotfun("n_words", "Number of words per combined note", q=True)
plotfun("u_words", "Number of unique words per combined note", q=True)


# numbers of words by number of conc notes
f, ax = plt.subplots()
nnn = list(set(conc_notes_df.n_notes))
pltlist = [conc_notes_df.u_words[conc_notes_df.n_notes == i] for i in nnn if i < 15]
ax.set_title('Unique words by number of concatenated notes')
ax.boxplot(pltlist)
plt.xlabel("Number of notes concatenated together")
plt.ylabel("Number of unique words")
plt.figure(figsize=(8, 8))
f.savefig(f'{figdir}nnotes_by_uwords.pdf')

# pull some random notes
np.random.seed(8675309)
kind = "lp"
for i in conc_notes_df.month.unique():
    if kind == "lp":
        sampdf = conc_notes_df[(conc_notes_df.month == i) &
                               (conc_notes_df.lowprob == True) &
                               (conc_notes_df.highprob == False) &
                               (conc_notes_df.n_comorb <5)]
        samp = np.random.choice(sampdf.shape[0], 1)
        towrite = sampdf.combined_notes.iloc[int(samp)]
        fi = f"batch_01_m{sampdf.month.iloc[int(samp)]}_{sampdf.PAT_ID.iloc[int(samp)]}.txt"
        with open(f'{outdir}/notes_output/batch_01/{fi}', "w") as f:
            f.write(towrite)
        kind = "hp"
    elif kind == "hp":
        sampdf = conc_notes_df[(conc_notes_df.month == i) &
                               (conc_notes_df.lowprob == False) &
                               (conc_notes_df.highprob == True) &
                               (conc_notes_df.n_comorb >15)]
        samp = np.random.choice(sampdf.shape[0], 1)
        towrite = sampdf.combined_notes.iloc[int(samp)]
        fi = f"batch_01_m{sampdf.month.iloc[int(samp)]}_{sampdf.PAT_ID.iloc[int(samp)]}.txt"
        with open(f'{outdir}/notes_output/batch_01/{fi}', "w") as f:
            f.write(towrite)
        kind = "lp"

# second batch of random notes
# pull some random notes
np.random.seed(5555555)
kind = "lp"
for i in conc_notes_df.month.unique():
    if kind == "lp":
        sampdf = conc_notes_df[(conc_notes_df.month == i) &
                               (conc_notes_df.lowprob == True) &
                               (conc_notes_df.highprob == False) &
                               (conc_notes_df.n_comorb <5)]
        samp = np.random.choice(sampdf.shape[0], 1)
        towrite = sampdf.combined_notes.iloc[int(samp)]
        fi = f"batch_02_m{sampdf.month.iloc[int(samp)]}_{sampdf.PAT_ID.iloc[int(samp)]}.txt"
        with open(f'{outdir}/notes_output/batch_02/{fi}', "w") as f:
            f.write(towrite)
        kind = "hp"
    elif kind == "hp":
        sampdf = conc_notes_df[(conc_notes_df.month == i) &
                               (conc_notes_df.lowprob == False) &
                               (conc_notes_df.highprob == True) &
                               (conc_notes_df.n_comorb >15)]
        samp = np.random.choice(sampdf.shape[0], 1)
        towrite = sampdf.combined_notes.iloc[int(samp)]
        fi = f"batch_02_m{sampdf.month.iloc[int(samp)]}_{sampdf.PAT_ID.iloc[int(samp)]}.txt"
        with open(f'{outdir}/notes_output/batch_02/{fi}', "w") as f:
            f.write(towrite)
        kind = "lp"


# 25 random notes from 2019
import os
np.random.seed(5446)
subset = conc_notes_df.loc[conc_notes_df.LATEST_TIME.dt.year == 2019]
previous = os.listdir(f"{outdir}notes_output/batch_01") + os.listdir(f"{outdir}notes_output/batch_02")
previds = [re.sub(".txt","", x.split("_")[-1]) for x in previous if '.pkl' not in x]
subsubset = subset.loc[~subset.PAT_ID.isin(previds)]
subsubsubset = subset.iloc[np.random.choice(subsubset.shape[0], 25)]
for i in range(25):
    towrite = subsubsubset.combined_notes.iloc[i]
    fi = f"batch_03_m{subsubsubset.month.iloc[i]}_{subsubsubset.PAT_ID.iloc[i]}.txt"
    with open(f'{outdir}/notes_output/batch_03/{fi}', "w") as f:
        f.write(towrite)


# 25 random notes from 2018
'''
NOTE THERE IS A TYPO BELOW.  I specified that the name of each of the files outputted would be "batch_03" when it should have been batch 4.  
This has no real consequences, but could cause confusion later, hence this note.  
I've made a post-hoc fix to the naming when the output gets loaded in the window classifier script.'
'''
import os
np.random.seed(266701)
subset = conc_notes_df.loc[conc_notes_df.LATEST_TIME.dt.year == 2018]
previous = os.listdir(f"{outdir}notes_output/batch_01") + os.listdir(f"{outdir}notes_output/batch_02") + \
           os.listdir(f"{outdir}notes_output/batch_03")
previds = [re.sub(".txt","", x.split("_")[-1]) for x in previous if '.pkl' not in x]
subsubset = subset.loc[~subset.PAT_ID.isin(previds)]
subsubsubset = subset.iloc[np.random.choice(subsubset.shape[0], 30)]
for i in range(30):
    towrite = subsubsubset.combined_notes.iloc[i]
    fi = f"batch_03_m{subsubsubset.month.iloc[i]}_{subsubsubset.PAT_ID.iloc[i]}.txt"
    if i < 25:
        fi = f"batch_03_m{subsubsubset.month.iloc[i]}_{subsubsubset.PAT_ID.iloc[i]}.txt"
    else:
        fi = f"batch_03_alternate_m{subsubsubset.month.iloc[i]}_{subsubsubset.PAT_ID.iloc[i]}.txt"
    with open(f'{outdir}/notes_output/batch_04/{fi}', "w") as f:
        f.write(towrite)

# 25 random notes from 2019
import os
np.random.seed(999)
subset = conc_notes_df.loc[conc_notes_df.LATEST_TIME.dt.year == 2019]
previous = os.listdir(f"{outdir}notes_output/batch_01") + os.listdir(f"{outdir}notes_output/batch_02") + \
           os.listdir(f"{outdir}notes_output/batch_03") + os.listdir(f"{outdir}notes_output/batch_04")
previds = [re.sub(".txt","", x.split("_")[-1]) for x in previous if '.pkl' not in x]
subsubset = subset.loc[~subset.PAT_ID.isin(previds)]
subsubsubset = subset.iloc[np.random.choice(subsubset.shape[0], 30)]
for i in range(30):
    towrite = subsubsubset.combined_notes.iloc[i]
    fi = f"batch_05_m{subsubsubset.month.iloc[i]}_{subsubsubset.PAT_ID.iloc[i]}.txt"
    if i < 25:
        fi = f"batch_05_m{subsubsubset.month.iloc[i]}_{subsubsubset.PAT_ID.iloc[i]}.txt"
    else:
        fi = f"batch_05_alternate_m{subsubsubset.month.iloc[i]}_{subsubsubset.PAT_ID.iloc[i]}.txt"
    with open(f'{outdir}/notes_output/batch_05/{fi}', "w") as f:
        f.write(towrite)


# 25 random notes from 2019
# batch 6
import os
np.random.seed(224)
subset = conc_notes_df.loc[conc_notes_df.LATEST_TIME.dt.year == 2019]
previous = os.listdir(f"{outdir}notes_output/batch_01") + os.listdir(f"{outdir}notes_output/batch_02") + \
           os.listdir(f"{outdir}notes_output/batch_03") + os.listdir(f"{outdir}notes_output/batch_04") + \
           os.listdir(f"{outdir}notes_output/batch_04")
previds = [re.sub(".txt","", x.split("_")[-1]) for x in previous if '.pkl' not in x]
subsubset = subset.loc[~subset.PAT_ID.isin(previds)]
subsubsubset = subset.iloc[np.random.choice(subsubset.shape[0], 30)]
for i in range(30):
    towrite = subsubsubset.combined_notes.iloc[i]
    fi = f"batch_06_m{subsubsubset.month.iloc[i]}_{subsubsubset.PAT_ID.iloc[i]}.txt"
    if i < 25:
        fi = f"batch_06_m{subsubsubset.month.iloc[i]}_{subsubsubset.PAT_ID.iloc[i]}.txt"
    else:
        fi = f"batch_06_alternate_m{subsubsubset.month.iloc[i]}_{subsubsubset.PAT_ID.iloc[i]}.txt"
    with open(f'{outdir}/notes_output/batch_06/{fi}', "w") as f:
        f.write(towrite)

