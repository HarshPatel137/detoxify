import csv, io, datetime as dt
def csv_export(rows):
    buf=io.StringIO(); w=csv.writer(buf)
    w.writerow(["timestamp_iso","toxicity","severe_toxicity","insult","threat","obscene","identity_attack"])
    for ts, sc in rows:
        iso=dt.datetime.utcfromtimestamp(ts).isoformat()+"Z"
        w.writerow([iso, sc.get("toxicity",0.0), sc.get("severe_toxicity",0.0), sc.get("insult",0.0),
                    sc.get("threat",0.0), sc.get("obscene",0.0), sc.get("identity_attack",0.0)])
    return buf.getvalue().encode()
