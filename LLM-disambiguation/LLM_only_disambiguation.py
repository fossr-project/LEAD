import pandas as pd
import ast  # Modulo per convertire stringhe in liste
import torch
import transformers
import json
import os
import time
from collections import defaultdict
import random
from utils import ssd_dict

os.environ["CUDA_VISIBLE_DEVICES"] = "0,1,2"

file_path = "/path/to/ground_truth"
df = pd.read_excel(file_path)

#save researchers' info in a dictionary with unique ID
ricercatori_dict = {}

for index, row in df.iterrows():
    ricercatore_id = row["id"]
    cognome = row["cognome"]
    nome = row["nome"]
    ssd = row["ssd"]
    universita = row["universita"]
    lista_auid = row["lista_auid"]
    unique_id = str(ricercatore_id) + '_' + str(lista_auid)

    ricercatori_dict[unique_id] = {

        "cerca_univ_id" : ricercatore_id,
        "cognome": cognome,
        "nome": nome,
        "ssd": ssd,
        "universita": universita,
        "lista_auid": lista_auid,
    }


def load_json_files(directory):
    all_data = []
    for filename in os.listdir(directory):
        if filename.endswith(".json"):
            file_path = os.path.join(directory, filename)
            try:
                with open(file_path, "r", encoding="utf-8") as file:
                    for line in file:
                        line = line.strip()
                        if line:
                            all_data.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON in file {filename}: {e}")
            except Exception as e:
                print(f"Error in file {filename}: {e}")
    return all_data

dir_scopus = "/path/to/directory/file_scopus"

# Load Scopus file
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

    # Author's list
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

print(len(authors_dict))

random.seed(3)
# Use this section only if you want to limit the analysis
# to 10 papers per author
kappa = 10
for auid, info in authors_dict.items():
    papers = info.get("papers", [])
    if len(papers) > kappa:
        # Randomly select 10 papers
        authors_dict[auid]["papers"] = random.sample(papers, kappa)
# Check that no author has more than 10 papers
over_limit = [(auid, len(info["papers"])) for auid, info in authors_dict.items() if len(info["papers"]) > kappa]

if over_limit:
    print(f"Authors with more than {kappa} papers:", over_limit)
else:
    print(f"All authors have at most {kappa} papers.")

local_model_path = "/path/to/LlaMa"

#check Academic Disciplines dictionary
print(len(ssd_dict))

# Load the model
model = transformers.AutoModelForCausalLM.from_pretrained(
    local_model_path,
    torch_dtype=torch.bfloat16,
    device_map="auto",
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

def format_author_info(author_id, author_info):
    papers = sorted(author_info["papers"], key=lambda x: x["year"], reverse=True)
    papers_str = ""
    for p in papers:
        title = p.get("title", "").strip()
        year = p.get("year", "").strip()
        #abstract = p.get("abstract", "").strip()[:300]
        keywords = p.get("keywords", [])
        # Se keywords è una stringa, prova a convertirla in lista
        if isinstance(keywords, str):
            keywords = [kw.strip() for kw in keywords.split(",") if kw.strip()]
        keywords_str = ", ".join(keywords) if keywords else "None"

        papers_str += (
            f"- [{year}] {title}"
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

###############
for k, v in ricercatori_dict.items():
    cerca_univ_id = v['cerca_univ_id']

    auid = str(v['lista_auid'])
    #Format author information for the matched candidate
    candidates_str = f"Candidate:\n{format_author_info(auid, authors_dict[auid])}"

    messages = [
        {
            "role": "system",
            "content": "Your task is to evaluate the candidate to determine if they match the specified researcher profile."
        }
        ,
        {
            "role": "user",
            "content": (
                f"Is the following candidate a match for the researcher {v['nome']} {v['cognome']}, affiliated with {v['universita']}, "
                f"working in the Italian academic field of {ssd_dict.get(v['ssd'], 'unknown field')}? "
                "The candidate's publications are listed in chronological order to help you analyze their research progression."
                f"Here is the candidate: {candidates_str}"
                "Based on the provided information, do you believe this candidate is the best match? Please respond with 'yes' if you believe this is the correct match, otherwise respond with 'no' and provide a brief explanation of your choice"
                "Respond only in JSON format as follows:"
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


    # Compute elapsed time in hours, minutes, and seconds for this iteration
    elapsed_time = end_time - start_time
    hours = int(elapsed_time // 3600)
    minutes = int((elapsed_time % 3600) // 60)
    seconds = int(elapsed_time % 60)
    print(f"Generation time for this iteration: {hours} h {minutes} min {seconds} sec")
    generated_text = outputs[0]["generated_text"][-1]
    cleaned_text = generated_text['content']
    print(cleaned_text)
    responses.append(cleaned_text)


total_end_time = time.time()

# Compute total time
total_elapsed_time = total_end_time - total_start_time
total_hours = int(total_elapsed_time // 3600)
total_minutes = int((total_elapsed_time % 3600) // 60)
total_seconds = int(total_elapsed_time % 60)
print(f"Total time: {total_hours} h {total_minutes} min {total_seconds} sec\n")

# Save all responses to a text file (one per line)
with open(f'output_kws_title_{kappa}_papers.txt', 'w', encoding='utf-8') as file:
    for response in responses:
        file.write(response + '\n')