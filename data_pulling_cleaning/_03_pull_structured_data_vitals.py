'''
This script pulls structured data for patient windows corresponding to what is in 'conc_notes_df', generated
in the previous script.

Vitals:  age, blood pressure, weight, height

'''
import os
import pandas as pd
from utils.misc import get_clarity_conn, get_from_clarity_then_save,     query_filtered_with_temp_tables, write_txt, read_txt, nrow
import re
import time
import multiprocessing as mp
import copy
import numpy as np

# preferences
pd.options.display.max_rows = 4000
pd.options.display.max_columns = 4000

# connect to the database
clar_conn = get_clarity_conn("/Users/crandrew/Documents/clarity_creds_ACD.yaml")

# set a global data dir for PHI
datadir = f"{os.getcwd()}/data/"
outdir = f"{os.getcwd()}/output/"

# load the concatenated notes DF
df = pd.read_pickle((f'{outdir}conc_notes_df.pkl'))

'''
vitals
'''

if "vitals_raw.pkl" not in os.listdir(datadir):
    bq = '''
select
        pe.PAT_ID
    ,   pe.PAT_ENC_CSN_ID
    ,   datediff(day, p.BIRTH_DATE, pe.CONTACT_DATE) / 365.0        as AGE
    ,   pe.CONTACT_DATE
    ,   pe.BP_DIASTOLIC
    ,   pe.BP_SYSTOLIC
    ,   pe.WEIGHT
    ,   pe.HEIGHT
    ,   pe2.PHYS_SPO2
from PAT_ENC as pe
join PATIENT as p on p.PAT_ID = pe.PAT_ID
join PAT_ENC_2 as pe2 on pe.PAT_ENC_CSN_ID = pe2.PAT_ENC_CSN_ID
    '''
    fdict = dict(PAT_ID={"vals": [], "foreign_key":"PAT_ID","foreign_table": "pe"})

    def wrapper(ids):
        start = time.time()
        fd = copy.deepcopy(fdict)
        fd['PAT_ID']['vals'] = ids
        q = query_filtered_with_temp_tables(bq, fd, rstring=str(np.random.choice(10000000000)))
        q += "where pe.CONTACT_DATE >= '2017-01-01'"
        out = get_from_clarity_then_save(q, clar_conn=clar_conn)
        # remove rows where none of the useful variables are measured
        out = out.loc[(~np.isnan(out.BP_DIASTOLIC)) |
                      (~np.isnan(out.BP_SYSTOLIC)) |
                      (~out.HEIGHT.isnull()) |
                      (~np.isnan(out.WEIGHT))]
        print(f"did file starting with {ids[0]}, and it's got {out.shape}.  it took {time.time()-start}")
        return out


    UIDs = df.PAT_ID.unique().tolist()
    UIDs.sort()
    chunks = [UIDs[(i*1000):((i+1)*1000)] for i in range(len(UIDs)//1000+1)]

    pool = mp.Pool(processes=mp.cpu_count())
    start = time.time()
    vitout = pool.map(wrapper, chunks, chunksize=1)
    print(time.time() - start)
    pool.close()

    vitdf = pd.concat(vitout)
    vitdf.to_pickle(f"{datadir}vitals_raw.pkl")
else:
    vitdf = pd.read_pickle(f"{datadir}vitals_raw.pkl")





## Output for cleaning in r
vitdf.to_csv(f"{outdir}/vitals_r_start.csv")

## Running R script & reading output
os.system("Rscript ./_03_pull_structured_data_vitals.R &")

## Set correct data types for reading
vitdf = pd.read_csv((f"{outdir}/vitals_r_finish.csv"),
                 dtype={"PAT_ID": object, 'PAT_ENC_CSN_ID': object, "AGE": np.float64, "BP_DIASTOLIC": np.float64,
                        "BP_SYSTOLIC": np.float64, "WEIGHT": np.float64, 
                        "HEIGHT_CM": np.float64, "BMI": np.float64,
                        "PHYS_SPO2": np.float64},
                    parse_dates = ["CONTACT_DATE"])

vitdf.head()

# clean the SPO2
vitdf.PHYS_SPO2.loc[vitdf.PHYS_SPO2 < 60] = np.nan

# pull the most recent CSN from the concatenated notes df
df['PAT_ENC_CSN_ID'] = df.CSNS.apply(lambda x: int(x.split(",")[0]))
df['month'] = df.LATEST_TIME.dt.month+(df.LATEST_TIME.dt.year-2018)*12

# write a function that takes a row of the concatenated notes DF and outputs a dict of vitals values
def recent_vits(i):
    try:
        vdf = vitdf.loc[(vitdf.PAT_ID == df.PAT_ID.iloc[i]) &
                        (vitdf.CONTACT_DATE <= df.LATEST_TIME.iloc[i] + pd.DateOffset(
                            days=1)) &  # the deals with the fact that the times might be rounded down to the nearest day sometimes
                        (vitdf.CONTACT_DATE >= df.LATEST_TIME.iloc[i] - pd.DateOffset(months=6))
                        ]
        if nrow(vdf) > 0:
            outdict = dict(PAT_ID = df.PAT_ID.iloc[i],
                           PAT_ENC_CSN_ID=df.PAT_ENC_CSN_ID.iloc[i],
                           month=df.month.iloc[i],
                           mean_sys_bp = vdf.BP_SYSTOLIC.mean(),
                           mean_dia_bp=vdf.BP_DIASTOLIC.mean(),
                           sd_sys_bp=vdf.BP_SYSTOLIC.std(),
                           sd_dia_bp=vdf.BP_DIASTOLIC.std(),
                           bmi_mean = vdf.BMI.mean(),
                           spo2_min = vdf.PHYS_SPO2.min())

            vdf['day'] = (vdf.CONTACT_DATE - pd.Timestamp("2017-01-01")).dt.days
            dd = vdf.loc[~vdf.BMI.isna(), ['day', 'BMI']]
            if nrow(dd) > 2:
                try:
                    X = np.vstack([np.ones(nrow(dd)), dd.day]).T
                    outdict['bmi_slope'] = (np.linalg.inv(X.T @ X) @ X.T @ dd.BMI)[1]
                except Exception:
                    pass

            return outdict
        else:
            return
    except Exception as e:
        print(f"======={i}======")
        print(e)
        return e



pool = mp.Pool(processes=mp.cpu_count())
start = time.time()
rvits = pool.map(recent_vits, range(nrow(df)), chunksize=1)
print(time.time() - start)
pool.close()


errs = [i for i in range(len(rvits)) if type(rvits[i]).__name__ != "dict"]
rvits_fixed = [i for i in rvits if type(i).__name__ == "dict"]

vits_6m = pd.DataFrame(rvits_fixed)





# added Apr18: get data from flow sheets.  this query comes from paul junker
bq = '''
SELECT DISTINCT
		peh.PAT_ENC_CSN_ID
	   ,peh.PAT_ID
       ,peh.HOSP_ADMSN_TIME
       ,peh.HOSP_DISCH_TIME
       ,fmea.FLO_MEAS_ID
       ,fdat.DISP_NAME
       ,fmea.MEAS_VALUE
       ,fmea.RECORDED_TIME
FROM
       IP_FLWSHT_REC AS frec2
       JOIN IP_FLWSHT_MEAS AS fmea ON fmea.FSD_ID = frec2.FSD_ID and fmea.MEAS_VALUE is not null
       JOIN IP_FLO_GP_DATA AS fdat ON fdat.FLO_MEAS_ID = fmea.FLO_MEAS_ID
       JOIN PAT_ENC_HSP peh ON peh.INPATIENT_DATA_ID = frec2.INPATIENT_DATA_ID
       '''
footer = '''
WHERE 1=1
	AND
		(fmea.FLO_MEAS_ID in('3040360013','1603015501','107000508','1073040277','1073040159','250026',
							'10','3040102560','3040311130','3040104328','3040104329')
		OR fmea.FLO_MEAS_ID in ('1120100067') and fmea.MEAS_VALUE NOT in ('none (room air)', 'other (comment)', 'T piece')
		)
    AND fmea.RECORDED_TIME >= '2017-01-01'
'''
fdict = dict(PAT_ID={"vals": [], "foreign_key":"PAT_ID","foreign_table": "peh"})
def wrapper(ids):
    start = time.time()
    fd = copy.deepcopy(fdict)
    fd['PAT_ID']['vals'] = ids
    q = query_filtered_with_temp_tables(bq, fd, rstring=str(np.random.choice(10000000000)))
    q += footer
    out = get_from_clarity_then_save(q, clar_conn=clar_conn)
    # remove rows where none of the useful variables are measured
    print(f"did file starting with {ids[0]}, and it's got {out.shape}.  it took {time.time()-start}")
    return out


UIDs = df.PAT_ID.unique().tolist()
UIDs.sort()
chunks = [UIDs[(i*1000):((i+1)*1000)] for i in range(len(UIDs)//1000+1)]

pool = mp.Pool(processes=mp.cpu_count())
start = time.time()
flwout = pool.map(wrapper, chunks, chunksize=1)
print(time.time() - start)
pool.close()

flowdf = pd.concat(flwout)
flowdf.head()
flowdf.DISP_NAME.value_counts()

# consolidate the O2 obs
flowdf.DISP_NAME.loc[flowdf.DISP_NAME.isin(['O2 Flow (L/min)', 'Flow (L/min)', 'O2 Flow Rate (L/min)'])] = "supp_O2_flow"

# lose the columns not in use
flowdf = flowdf.loc[flowdf.DISP_NAME.isin(['SpO2', 'supp_O2_flow'])]
# set it to float
flowdf.MEAS_VALUE = flowdf.MEAS_VALUE.astype(float)

flowdf.MEAS_VALUE.loc[flowdf.DISP_NAME == 'SpO2'].astype(float).hist()
flowdf.MEAS_VALUE.loc[flowdf.DISP_NAME == 'supp_O2_flow'].astype(float).hist()

flowdf.MEAS_VALUE.loc[(flowdf.DISP_NAME == 'supp_O2_flow') & (flowdf.MEAS_VALUE > 100)] = np.nan

# write a function that takes a row of the concatenated notes DF and outputs a dict of vitals values
def recent_flow(i):
    try:
        fdf = flowdf.loc[(flowdf.PAT_ID == df.PAT_ID.iloc[i]) &
                        (flowdf.RECORDED_TIME <= df.LATEST_TIME.iloc[i] + pd.DateOffset(
                            days=1)) &  # the deals with the fact that the times might be rounded down to the nearest day sometimes
                        (flowdf.RECORDED_TIME >= df.LATEST_TIME.iloc[i] - pd.DateOffset(months=6))
                        ]
        if nrow(fdf) > 0:
            outdict = dict(PAT_ID = df.PAT_ID.iloc[i],
                           PAT_ENC_CSN_ID=df.PAT_ENC_CSN_ID.iloc[i],
                           month=df.month.iloc[i],
                           spo2_min = fdf.MEAS_VALUE.loc[fdf.DISP_NAME == "SpO2"].min(),
                           max_o2 = fdf.MEAS_VALUE.loc[fdf.DISP_NAME == "supp_O2_flow"].max())
            fdf['day'] = (fdf.RECORDED_TIME - pd.Timestamp("2017-01-01")).dt.days

            return outdict
        else:
            return
    except Exception as e:
        print(f"======={i}======")
        print(e)
        return e


pool = mp.Pool(processes=mp.cpu_count())
start = time.time()
rflow = pool.map(recent_flow, range(nrow(df)), chunksize=1)
print(time.time() - start)
pool.close()


errs = [i for i in range(len(rflow)) if type(rflow[i]).__name__ != "dict"]
rflow_fixed = [i for i in rflow if type(i).__name__ == "dict"]

flow_6m = pd.DataFrame(rflow_fixed)
flow_6m = flow_6m.rename(columns={"spo2_min":"xx"})
# combine the two data frames, take the min of spo2
xx = vits_6m.merge(flow_6m, how = "outer")
xx["spo2_worst"] = np.nan
for i in range(xx.shape[0]):
    xx["spo2_worst"].iloc[i] = xx.spo2_min.iloc[i] if (xx.spo2_min.iloc[i] < xx.xx.iloc[i] or np.isnan(xx.xx.iloc[i])) else xx.xx.iloc[i]


xx.drop(columns = ["spo2_min", 'xx'], inplace = True)

xx.head()
xx.shape



xx.to_pickle(f"{outdir}vits_6m.pkl")

