import pandas as pd
import ast
import math




import pandas as pd
import ast  # Modulo per convertire stringhe in liste
import torch
import transformers
import json
import os
import time
from collections import defaultdict
import random
from tqdm import tqdm
from utils import ssd_dict, area_dict, macro_sc_dict, sc_dict
os.environ["CUDA_VISIBLE_DEVICES"] = "0,1,2"

file_path = "/path/to/ground_truth_with_BC_info.xlsx"
df = pd.read_excel(file_path)

def to_papers_list(val):
    if val is None or (isinstance(val, float) and math.isnan(val)) or (isinstance(val, str) and not val.strip()):
        return []
    if isinstance(val, list) or isinstance(val, tuple):
        return [str(x) for x in val]
    if isinstance(val, (int, float)):
        return [str(int(val))] if float(val).is_integer() else [str(val)]
    if isinstance(val, str):
        s = val.strip()
        # caso: stringa che rappresenta una lista
        if s.startswith('[') and s.endswith(']'):
            try:
                parsed = ast.literal_eval(s)
                if isinstance(parsed, (list, tuple)):
                    return [str(x) for x in parsed]
                return [str(parsed)]
            except Exception:
                pass

        parts = [p.strip() for p in s.split(',') if p.strip()]
        return parts or [s]

    return [str(val)]
ricercatori_dict = {}

for index, row in df.iterrows():
    ricercatore_id = row["id"]
    cognome = row["cognome"]
    nome = row["nome"]
    ssd = row["ssd"]
    scp = row["scp"]
    macro_scp = row["macro_scp"]
    area_p = row["area_p"]
    papers = row["papers"]
    cited_papers = row["cited_papers"]
    num_match = row["num_match"]
    overlap_p = row["perc_match_2016_2023"]
    papers_IDS = to_papers_list(row["papers_IDS"])
    universita = row["universita"]
    lista_auid = row["auid"]
    unique_id = str(ricercatore_id) + '_' + str(lista_auid)


    ricercatori_dict[unique_id] = {

        "cerca_univ_id" : ricercatore_id,
        "cognome": cognome,
        "nome": nome,
        "ssd": ssd,
        "scp": scp,
        "macro_scp":macro_scp,
        "area_p":area_p ,
        "overlap_p":overlap_p,
        "papers": papers,
        "cited_papers":cited_papers,
        "num_match":num_match,
        "universita": universita,
        "papers_IDS": papers_IDS,
        "lista_auid": lista_auid,

    }


def load_json_files(directory):
    all_data = []
    for filename in tqdm(os.listdir(directory), desc="Loading json files"):
        if filename.endswith(".json"):
            file_path = os.path.join(directory, filename)
            try:
                with open(file_path, "r", encoding="utf-8") as file:
                    for line in file:
                        line = line.strip()
                        if line:
                            all_data.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"Errore nella decodifica del JSON nel file {filename}: {e}")
            except Exception as e:
                print(f"Errore nel file {filename}: {e}")
    return all_data

dir_scopus  = "/path/to/directory/scopus_papers_files"

json_scopus_papers = load_json_files(dir_scopus)
scopus_dict = defaultdict(lambda: {"papers": [], "anni": set()})


for paper in json_scopus_papers:
    paper_id = paper.get("_id")
    year = paper.get("prism:coverDisplayDate", "")[-4:]
    for author in paper.get("author", []):
        auid = author.get("authid")
        if auid:
            scopus_dict[auid]["papers"].append(paper_id)
            scopus_dict[auid]["anni"].add(year)

authors_dict = {}
# Metadata extraction from scopus papers
for paper in json_scopus_papers:
    paper_id = paper.get("_id")
    # Uncomment the desired lines to include specific metadata
    title = paper.get("dc:title", "")
    #abstract = paper.get("dc:description", "")
    year = paper.get("prism:coverDisplayDate", "")
    keywords = paper.get("authkeywords", "")


    for author in paper.get("author", []):
        author_id = author.get("authid")
        given_name = author.get("given-name", "")
        surname = author.get("surname", "")
        initials = author.get("initials", "")
        aff_ids = [aff["$"] for aff in author.get("afid", [])]

        full_name = f"{given_name} {surname}"


        aff_names = []
        for aff in paper.get("affiliation", []):
            if aff.get("afid") in aff_ids:
                aff_names.append(aff.get("affilname", ""))

        if author_id in authors_dict:
            authors_dict[author_id]["papers"].append({
                "paper_id": paper_id,
                "title": title,
                #"abstract": abstract,
                "year": year,
                "keywords": keywords
            })
            authors_dict[author_id]["affiliations"].update(aff_names)
        else:

            authors_dict[author_id] = {
                "given_name": given_name,
                "surname": surname,
                "initials": initials,
                "full_name": full_name,
                "affiliations": set(aff_names),
                "papers": [{
                    "paper_id": paper_id,
                     "title": title,
                    #"abstract": abstract,
                    "year": year,
                    "keywords": keywords
                }]
            }


#random.seed(3)

local_model_path = "/path/to/Llama"

#print(len(ssd_dict))
# Caricamento del modello quantizzato in 8-bit
model = transformers.AutoModelForCausalLM.from_pretrained(
    local_model_path,
    torch_dtype=torch.bfloat16,  # Usa bfloat16 per ridurre il consumo di memoria
    device_map="auto",
   #load_in_4bit=True  # Usa int8 (senza torch_dtype)
)

tokenizer = transformers.AutoTokenizer.from_pretrained(local_model_path)
pipeline = transformers.pipeline(
    "text-generation",
    model=model,
    tokenizer=tokenizer
)

####
responses = []
total_start_time = time.time()

def format_author_info_original(author_id, author_info):
    papers = sorted(author_info["papers"], key=lambda x: x["year"], reverse=True)
    #print("Num papers:",len(papers))
    papers_str = ""
    for p in papers:
        title = p.get("title", "").strip()
        year = p.get("year", "").strip()
        #abstract = p.get("abstract", "").strip()[:300]
        keywords = p.get("keywords", [])

        if isinstance(keywords, str):
            keywords = [kw.strip() for kw in keywords.split(",") if kw.strip()]
        keywords_str = ", ".join(keywords) if keywords else "None"

        papers_str += (
           f"- [{year}] - {title}"
            #f" -   Abstract: {abstract}"
            f" - Keywords: {keywords_str}"
        )

    affiliations = "; ".join(author_info["affiliations"])
    return (
        f"Author ID: {author_id}\n"
        f"Name: {author_info['full_name']}\n"
        f"Surname: {author_info['surname']}\n"
        f"Initials: {author_info['initials']}\n"
        f"Affiliations: {affiliations}\n"
        f"Publications (chronological order):{papers_str}"
    )

def format_author_info(author_id, author_info, papers_IDS):
    idset = set(to_papers_list(papers_IDS))

    selected = [p for p in author_info.get("papers", [])
                if str(p.get("paper_id")) in idset]

    selected = sorted(selected, key=lambda x: x["year"], reverse=True)

    papers_str = ""
    for p in selected:
        title = (p.get("title") or "").strip()
        year = (p.get("year") or "").strip()
        kws = p.get("keywords", [])
        if isinstance(kws, str):
            kws = [kw.strip() for kw in kws.split(",") if kw.strip()]
        keywords_str = ", ".join(kws) if kws else "None"
        papers_str += f"- [{year}] - {title} - Keywords: {keywords_str}"

    affiliations = "; ".join(sorted(list(author_info.get("affiliations", []))))
    return (
        f"Author ID: {author_id}\n"
        f"Name: {author_info['full_name']}\n"
        f"Surname: {author_info['surname']}\n"
        f"Initials: {author_info['initials']}\n"
        f"Affiliations: {affiliations}\n"
        f"Publications (chronological order):{papers_str}"
    )

for k, v in ricercatori_dict.items():
    cerca_univ_id = v['cerca_univ_id']
    auid = str(v['lista_auid'])
    papers_IDS = v['papers_IDS']
    candidates_str = f"Candidate:\n{format_author_info(auid, authors_dict[auid], papers_IDS)}"
    scp = v["scp"]
    ssd = v["ssd"]
    macroscp = v["macro_scp"]


    area = str(int(v["area_p"])) if pd.notna(v["area_p"]) else "unknown"

    overlap = v["overlap_p"]
    papers = v["papers"]
    cited_papers = v["cited_papers"]
    num_match = v["num_match"]

    try:
        overlap_float = float(v["overlap_p"]) * 100
    except:
        overlap_float = 0.0


    ssd_label = ssd_dict.get(ssd, "unknown field")
    scp_label = sc_dict.get(scp, "unknown macro sector")
    macroscp_label = macro_sc_dict.get(macroscp, "unknown macro-sector")  # se vuoi renderlo più descrittivo
    area_label = area_dict.get(area, "unknown area")
    citation_part = (

        f"1.An analysis of citations through a citation network has shown that {overlap_float:.1f} %"
        f"of the citations in the candidate's {papers} papers (which cite a total of {cited_papers} papers) align with those of the academic community,"
        f"with {num_match} relevant citations found in the network"

    )
    coauthorship_part = (
        "2. A method based on a co-authorship network has predicted the following academic classification:\n"
        f"   - Recruitment field: {scp} - {scp_label}\n"
        f"   - Macro recruitment field: {macroscp} - {macroscp_label}\n"
        f"   - Area: {area} - {area_label}\n\n"
    )

    #set the threshold
    if overlap < 0.10:
        messages = [
            {
                "role": "system",
                "content": "Your task is to evaluate the candidate to determine if they match the specified researcher profile."
            },
            {
                "role": "user",
                "content": (
                    f"Is the following candidate a match for the researcher {v['nome']} {v['cognome']}, affiliated with {v['universita']}, "
                    f"working in the Italian academic field of {ssd_label}?\n\n"
                    "You also have additional information obtained through automated methods, which may contain inaccuracies. Please use this information critically to support your evaluation:\n"
                    f"{citation_part}"
                    f"{coauthorship_part}"
                    "The candidate's publications are listed in chronological order to help you analyze their research progression.\n"
                    f"{candidates_str}\n\n"
                    "Based on the provided information, do you believe this candidate is the best match for the researcher? "
                    "Please respond with 'yes' if you believe this is the correct match, otherwise respond with 'no' and provide a brief explanation of your choice.\n\n"
                    "Respond only in JSON format as follows:\n"
                    f"{{'cerca_univ_id': {cerca_univ_id}, 'scopus_candidate_id': candidate's id, 'match': 'yes' or 'no', 'explanation': 'Your explanation here.'}}"
                )
            }
        ]

        start_time = time.time()


        outputs = pipeline(
            messages,
            max_new_tokens=700,
            temperature=0.00001,
            top_k = 1
        )
        end_time = time.time()

        elapsed_time = end_time - start_time
        hours = int(elapsed_time // 3600)
        minutes = int((elapsed_time % 3600) // 60)
        seconds = int(elapsed_time % 60)
        print(f"Tempo di generazione per questa iterazione: {hours} h {minutes} min {seconds} sec")
        generated_text = outputs[0]["generated_text"][-1]
        cleaned_text = generated_text['content']
        print(cleaned_text)
        responses.append(cleaned_text)



total_end_time = time.time()


total_elapsed_time = total_end_time - total_start_time
total_hours = int(total_elapsed_time // 3600)
total_minutes = int((total_elapsed_time % 3600) // 60)
total_seconds = int(total_elapsed_time % 60)
print(f"Total time: {total_hours} h {total_minutes} min {total_seconds} sec\n")


with open(f'responses_LEAD.txt', 'w', encoding='utf-8') as file:
    for response in responses:
        file.write(response + '\n')