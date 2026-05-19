import re
import json
import pandas as pd
import ast

with open("path/to/LLM_responses.txt") as f:
    text = f.read()


pattern = r"(?:```(?:json)?\s*)?(\{\s*['\"]cerca_univ_id['\"].*?\})(?:\s*```)?"
matches = re.findall(pattern, text, flags=re.DOTALL)

print(f"Number of extracted blocks:{len(matches)}")


parsed = []
for m in matches:
    s = m.strip()
    try:
        parsed.append(json.loads(s))
    except Exception:
        try:
            obj = ast.literal_eval(s)
            if isinstance(obj, dict):
                parsed.append(obj)
            else:
                print("⚠️ Blocco non è un dict, saltato.")
        except Exception as e:
            print("⚠️ Impossibile fare parse di un blocco. Errore:", e)

df = pd.DataFrame(parsed)
#save responses in a xlsx file
df.to_excel("responses.xlsx", index=False)
