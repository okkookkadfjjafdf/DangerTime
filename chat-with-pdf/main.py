import streamlit as st
import chromadb
import openai

from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential
from tabulate import tabulate
from chromadb.utils import embedding_functions
from chromadb import Client 

# You'll need this client later to store PDF data
client = chromadb.Client()
client.heartbeat()

# Logging the start of the application
print("Application started")

st.write("# Understanding a Benefits PDF")

uploaded_file = st.file_uploader("Choose a PDF file", type="pdf")

if uploaded_file is not None:
    print("PDF uploaded")
    # Create a temporary file to write the bytes to
    with open("temp_pdf_file.pdf", "wb") as temp_file:
        temp_file.write(uploaded_file.read())
    print("Temporary PDF file created")

    AZURE_COGNITIVE_ENDPOINT = "https://gengen.cognitiveservices.azure.com/"
    AZURE_API_KEY = "74c2d12f1098435e93bfed83f149f0e2"
    credential = AzureKeyCredential(AZURE_API_KEY)
    AZURE_DOCUMENT_ANALYSIS_CLIENT = DocumentAnalysisClient(AZURE_COGNITIVE_ENDPOINT, credential)

    # Open the temporary file in binary read mode and pass it to Azure
    with open("temp_pdf_file.pdf", "rb") as f:
        print("Analyzing document with Azure Document Analysis Client")
        poller = AZURE_DOCUMENT_ANALYSIS_CLIENT.begin_analyze_document("prebuilt-document", document=f)
        doc_info = poller.result().to_dict()
    print("Document analysis completed")

    res = []
    CONTENT = "content"
    PAGE_NUMBER = "page_number"
    TYPE = "type"
    RAW_CONTENT = "raw_content"
    TABLE_CONTENT = "table_content"

    # Processing document pages
    for p in doc_info['pages']:
        dict = {}
        page_content = " ".join([line["content"] for line in p["lines"]])
        dict[CONTENT] = str(page_content)
        dict[PAGE_NUMBER] = str(p["page_number"])
        dict[TYPE] = RAW_CONTENT
        res.append(dict)
    print("Processed document pages")

    # Processing tables
    for table in doc_info["tables"]:
        dict = {}
        dict[PAGE_NUMBER] = str(table["bounding_regions"][0]["page_number"])
        col_headers = []
        cells = table["cells"]
        for cell in cells:
            if cell["kind"] == "columnHeader" and cell["column_span"] == 1:
                for _ in range(cell["column_span"]):
                    col_headers.append(cell["content"])

        data_rows = [[] for _ in range(table["row_count"])]
        for cell in cells:
            if cell["kind"] == "content":
                for _ in range(cell["column_span"]):
                    data_rows[cell["row_index"]].append(cell["content"])
        data_rows = [row for row in data_rows if len(row) > 0]

        markdown_table = tabulate(data_rows, headers=col_headers, tablefmt="pipe")
        dict[CONTENT] = markdown_table
        dict[TYPE] = TABLE_CONTENT
        res.append(dict)
    print("Processed tables")

    try:
        client.delete_collection(name="my_collection")
        st.session_state.messages = []
    except Exception as e:
        print(f"Error deleting collection: {e}")

    openai_ef = embedding_functions.OpenAIEmbeddingFunction(api_key="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", model_name="text-embedding-ada-002")
    collection = client.create_collection(name="my_collection", embedding_function=openai_ef)
    print("Collection created")

    id = 1
    for dict in res:
        content = dict.get(CONTENT, '')
        page_number = dict.get(PAGE_NUMBER, '')
        type_of_content = dict.get(TYPE, '')

        content_metadata = {   
            PAGE_NUMBER: page_number,
            TYPE: type_of_content
        }

        collection.add(
            documents=[content],
            metadatas=[content_metadata],
            ids=[str(id)]
        )
        print(f"Added document ID {id} to the collection")
        # print(content)

        file_path = "response.txt"

        # Open the file in append mode ('a') and write the response
        with open(file_path, "a") as file:
            file.write(content + "\n")  # Add a newline character to separate responses

        print("Content appended to text file")

        id += 1

if "messages" not in st.session_state:
    st.session_state.messages = []

# Display chat messages from history on app rerun
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt := st.chat_input("What do you want to say to your PDF?"):
    # Display your message
    with st.chat_message("user"):
        st.markdown(prompt)
    # Add your message to chat history
    st.session_state.messages.append({"role": "user", "content": prompt})

    # query ChromaDB based on your prompt, taking the top 5 most relevant result. These results are ordered by similarity.
    print("Querying ChromaDB...")
    q = collection.query(
        query_texts=[prompt],
        n_results=5,
    )
    results = q["documents"][0]

    prompts = []
    for r in results:
        # construct prompts based on the retrieved text chunks in results 
        prompt_text = "Please extract the following: " + prompt + " solely based on the text below. Use an unbiased and journalistic tone. If you're unsure of the answer, say you cannot find the answer. \n\n" + r
        prompts.append(prompt_text)
    prompts.reverse()

    print("Sending prompts to OpenAI...")
    openai_res = openai.ChatCompletion.create(
        model="gpt-4",
        messages=[{"role": "assistant", "content": prompt} for prompt in prompts],
        temperature=0,
    )

    response = openai_res["choices"][0]["message"]["content"]

    # Escape dollar signs to prevent them from messing up Markdown rendering
    escaped_response = response.replace("$", "\\$")

    with st.chat_message("assistant"):
        # Use the escaped response for Markdown rendering
        st.markdown(escaped_response)

    # Append the original (or escaped, depending on your preference) response to chat history
    st.session_state.messages.append({"role": "assistant", "content": response})
    print("Response appended to chat history")
