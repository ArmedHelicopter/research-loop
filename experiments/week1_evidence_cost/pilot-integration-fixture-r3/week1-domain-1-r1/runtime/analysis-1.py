import pandas as pd,json
d=pd.read_csv('/input/data')
p={'rows':len(d),'columns':{}}
for c in d:
 s=d[c]; v={'dtype':str(s.dtype),'missing':int(s.isna().sum()),'unique':int(s.nunique())}
 if pd.api.types.is_numeric_dtype(s):
  v.update(min=float(s.min()) if s.notna().any() else None,max=float(s.max()) if s.notna().any() else None)
 else:v['examples']=[str(x)[:100] for x in s.dropna().unique()[:3]]
 p['columns'][str(c)]=v
print(json.dumps(p,allow_nan=False))
