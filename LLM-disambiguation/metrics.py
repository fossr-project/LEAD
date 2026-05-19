import pandas as pd
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score, classification_report, confusion_matrix

resp = pd.read_excel(/"path/to/responses.xlsx")
gt = pd.read_excel("/path/to/ground_truth.xlsx")

resp = resp.copy()
gt = gt.copy()

for c in ["cerca_univ_id", "scopus_candidate_id"]:
    resp[c] = resp[c].astype(str).str.strip()

for c in ["id", "auid"]:
    gt[c] = gt[c].astype(str).str.strip()

resp = (
    resp
    .dropna(subset=["cerca_univ_id","scopus_candidate_id"])
    .drop_duplicates(subset=["cerca_univ_id","scopus_candidate_id"], keep="last")
)


coverage = resp.merge(
    gt[["id","auid"]], how="left",
    left_on=["cerca_univ_id","scopus_candidate_id"],
    right_on=["id","auid"], indicator=True
)

# Check which candidate pairs from 'resp' are present in ground truth (gt)
missing = coverage[coverage["_merge"] == "left_only"]

# Print summary stats
print(f"🔎 Total pairs in resp: {len(resp)}")
print(f"✅ Pairs found in gt: {len(resp) - len(missing)}")
print(f"❌ Pairs missing in gt: {len(missing)}")

# If there are missing pairs, show a sample
if len(missing):
    print(missing[["cerca_univ_id", "scopus_candidate_id"]].head())

gt = gt.merge(
    resp.rename(columns={"cerca_univ_id":"id","scopus_candidate_id":"auid"})[["id","auid","match"]],
    on=["id","auid"], how="left"
)
gt.rename(columns={"match":"pred"}, inplace=True)
gt["pred"] = gt["pred"].map(lambda x: 1 if str(x).strip().lower()=="yes"
                                       else (0 if str(x).strip().lower()=="no" else pd.NA))


gt["pred"] = gt["pred"].fillna(1).astype(int)
gt["correct"] = gt["correct"].astype(int)
gt["pred"] = gt["pred"].astype(int)


y_true = gt["correct"].values
y_pred = gt["pred"].values

print("\n== scikit-learn ==")
print("Accuracy:", accuracy_score(y_true, y_pred))
print("Precision (binary):", precision_score(y_true, y_pred, zero_division=0))
print("Recall (binary):", recall_score(y_true, y_pred, zero_division=0))
print("F1 (binary):", f1_score(y_true, y_pred, zero_division=0))

# Report per class (0 and 1)
report = classification_report(y_true, y_pred, output_dict=True, zero_division=0)
print(f"\nClasse 0 -> Precision: {report['0']['precision']:.4f}, Recall: {report['0']['recall']:.4f}, F1: {report['0']['f1-score']:.4f}")
print(f"Classe 1 -> Precision: {report['1']['precision']:.4f}, Recall: {report['1']['recall']:.4f}, F1: {report['1']['f1-score']:.4f}")

# (Optional) confusion matrix
cm = confusion_matrix(y_true, y_pred, labels=[0,1])
print("\nMatrice di confusione (righe=verità [0,1], colonne=pred [0,1]):\n", cm)