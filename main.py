# pip install scipy sklearn
import json
import os.path as op
import time
from typing import Dict, List

import openai
import tiktoken
from scipy import spatial

import chatgpt
from pywebio.input import *
from pywebio.output import *
from pywebio.session import set_env

CHATGPT_MODEL = "gpt-3.5-turbo"  # or 'gpt-4'
DOC_CONTEXT_TOKENS = 1000

here_dir = op.dirname(op.abspath(__file__))
pywebio_docs = json.load(open(op.join(here_dir, 'doc-sections.json')))
gh_data = json.load(open(op.join(here_dir, 'github-dump.json')))

# Load the cl100k_base tokenizer which is designed to work with the ada-002 model
tokenizer = tiktoken.get_encoding("cl100k_base")


def get_embedding(text, api_key, **kwargs) -> List[float]:
    resp = openai.Embedding.create(
        input=text,
        engine="text-embedding-ada-002",
        api_key=api_key,
        **kwargs,
    )
    return resp["data"][0]["embedding"]


def get_related_issues_and_discussions(embedding: List[float], cnt=10):
    gh_issues = gh_data['issues']
    gh_discussions = gh_data['discussions']

    related_issues = sorted(gh_issues, key=lambda x: spatial.distance.cosine(embedding, x['embedding']))
    related_discussions = sorted(gh_discussions, key=lambda x: spatial.distance.cosine(embedding, x['embedding']))
    return related_issues[:cnt], related_discussions[:cnt]


def get_related_docs(embedding: List[float], max_tokens=1000) -> List[Dict]:
    sorted_docs = sorted(pywebio_docs, key=lambda x: spatial.distance.cosine(embedding, x['embedding']))

    related = []
    token_cnt = 0
    for doc in sorted_docs:
        t = len(tokenizer.encode(doc['content']))
        token_cnt += t
        related.append(doc)
        if token_cnt > max_tokens:
            break
    return related


def main():
    """PyWebIO QA ChatGPT Bot"""

    set_env(input_panel_fixed=False, output_animation=False)
    put_markdown("""
    # PyWebIO QA Bot 🤖️
    Ask a question about PyWebIO, then it will give you the related github issues and discussions and try to 
    answer your question from PyWebIO doc.
    """)
    openai_config = chatgpt.get_openai_config()
    question = textarea(rows=3,
                        placeholder="Input your question when using PyWebIO. (e.g., how to output matplotlib chart)")
    try:
        with put_loading('grow', 'info'):
            embedding = get_embedding(question, api_key=openai_config['api_key'], api_base=openai_config['api_base'])
    except Exception as e:
        put_error("Error in get embedding of question", e)
        return
    put_info(put_text(question, inline=True))

    related_issues, related_discussions = get_related_issues_and_discussions(embedding, cnt=5)
    related_docs = get_related_docs(embedding, max_tokens=DOC_CONTEXT_TOKENS)
    issue_links = '\n'.join(
        f" - [{i['title']}]({i['url']})"
        for i in related_issues
    )
    discussion_links = '\n'.join(
        f" - [{i['title']}]({i['url']})"
        for i in related_discussions
    )
    put_markdown(f"## Related Resources\nIssues:\n{issue_links}\n\nDiscussions:\n{discussion_links}")

    system_msg = (
        'Answer the question about the PyWebIO python package based on the context below,'
        'and if the question can\'t be answered based on the context, say "I don\'t know"'
    )
    context_prompt = "\n\n".join(
        doc['content']
        for doc in related_docs
    )
    messages = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": f"Context: \n{context_prompt}"},
    ]
    bot = chatgpt.ChatGPT(
        messages=messages,
        api_key=openai_config['api_key'],
        api_base=openai_config['api_base'],
        model=CHATGPT_MODEL
    )
    put_markdown("## ChatGPT Answers")
    put_warning(
        "Noted that the answer is generated by AI, and may not be correct."
        "Please be cautious and critically evaluate the responses."
    )
    while True:
        with use_scope(f'reply-{int(time.time())}'):
            put_loading('grow', 'info')
            try:
                reply_chunks = bot.ask_stream(f"Question: \n{question}")
            except Exception as e:
                popup('ChatGPT Error', put_error(e))
                break
            finally:
                clear()  # clear loading
            for chunk in reply_chunks:
                put_text(chunk, inline=True)
            clear()  # clear above text
            put_markdown(reply_chunks.result())
        if bot.latest_finish_reason() == 'length':
            put_error('Incomplete model output due to max_tokens parameter or token limit.')
        elif bot.latest_finish_reason() == 'content_filter':
            put_warning("Omitted content due to a flag from OpanAI's content filters.")

        question = textarea(placeholder="Follow up question", rows=3)
        put_info(put_text(question, inline=True))


if __name__ == '__main__':
    from pywebio import start_server

    start_server(main, port=8080, cdn=False)
