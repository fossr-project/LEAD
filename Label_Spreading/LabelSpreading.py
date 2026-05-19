import numpy as np
import networkx as nx
import matplotlib.pyplot as plt
import pandas as pd
from sklearn.semi_supervised import LabelSpreading
import time

def label_propagation(G, attribute_key):

    label_names = list({G.nodes[v][attribute_key] for v in G.nodes() if attribute_key in G.nodes[v]})
    label_indices = {label: i for i, label in enumerate(label_names)}
    print("Numero di etichette uniche:", len(label_names))


    W = nx.to_scipy_sparse_array(G, format='csr')


    y = -1 * np.ones(len(G), dtype=int)
    for i, v in enumerate(G.nodes()):
        if attribute_key in G.nodes[v]:
            y[i] = label_indices[G.nodes[v][attribute_key]]



    model = LabelSpreading(kernel=lambda W, _: W, alpha=0.2)
    start_time = time.time()
    model.fit(W, y)
    end_time = time.time()

    print(f"Elapsed time for label propagation: {end_time - start_time:.4f} seconds")

    # Etichette predette → nomi originali
    predicted_labels = model.transduction_
    final_labels = {i: label_names[predicted_labels[i]] for i in range(len(G))}


    for i, v in enumerate(G.nodes()):
        G.nodes[v][attribute_key + 'p'] = final_labels[i]


# === MAIN ===

#Load the graph
G = nx.read_graphml("graph_coauthors.xml")

#Select the key accordingly:  sc=>Recruitment Fields, macro_sc=>Groups, area=>Scientific Areas
#attribute_key = sc
#attribute_key = 'macrosc'
attribute_key = 'area'

num_nodes_without_label = sum(1 for v in G.nodes() if attribute_key not in G.nodes[v])
print("Nodes without label:", num_nodes_without_label)


df = pd.read_excel("/path/to/ground_truth.xlsx")
unique_ids = df['lista_auid'].astype(str).unique()

ids_without_scp = [node_id for node_id in unique_ids if 'scp' not in G.nodes.get(str(node_id), {})]
print(f"Totale ID nel DataFrame: {len(unique_ids)}")
print(f"ID senza label 'scp': {len(ids_without_scp)}")
target_ids = set(df['lista_auid'].astype(str).unique())

for node_id in target_ids:
    if node_id in G.nodes:
        G.nodes[node_id].pop('sc', None)


#predict labels
label_propagation(G, attribute_key)


# Save graphs with label propagated
nx.write_graphml(G, "graph_coauthors_2019-2024_macroscp_rielaborato.xml")

