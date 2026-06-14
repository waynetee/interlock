"""Inference compute node: serves Llama-2-7B over a TCP socket.

Two JSON ops (one persistent connection, length-prefixed):
  {"op":"gen",   "prompt": "...", "max_new": 24}   -> {"tokens": [ids]}
  {"op":"score", "prompt": "...", "tokens": [ids]} -> {"argmax": [ids]}

'gen' is greedy decoding (the workload). 'score' teacher-forces the given
response and returns the model's greedy prediction at each position; the
caller turns matches/mismatches into the unexplained-information bound U.
The same model instance backs both — 'score' is a stateless re-scoring of a
supplied (prompt, response), so it cannot replay a remembered output.
"""
import json
import os
import socket

import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from transport import send_msg, recv_msg

MODEL = os.environ.get("MODEL_DIR", "/home/claude/models/llama-2-7b-hf")
BIND = os.environ.get("COMPUTE_BIND", "0.0.0.0")   # 0.0.0.0 so a remote client (MacBook) can reach it
PORT = int(os.environ.get("COMPUTE_PORT", 5555))


def load():
    tok = AutoTokenizer.from_pretrained(MODEL)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    for kw in ({"dtype": torch.float16}, {"torch_dtype": torch.float16}):
        try:
            m = AutoModelForCausalLM.from_pretrained(MODEL, **kw).cuda().eval()
            return tok, m
        except TypeError:
            continue
    return tok, AutoModelForCausalLM.from_pretrained(MODEL).half().cuda().eval()


@torch.no_grad()
def handle(tok, model, req):
    prompt_ids = tok(req["prompt"], return_tensors="pt").input_ids.cuda()
    if req["op"] == "gen":
        out = model.generate(prompt_ids, max_new_tokens=req.get("max_new", 24),
                             do_sample=False, pad_token_id=tok.eos_token_id)
        new = out[0, prompt_ids.shape[1]:].tolist()
        return {"tokens": new, "text": tok.decode(new)}
    if req["op"] == "score":
        resp = torch.tensor(req["tokens"], device="cuda").unsqueeze(0)
        seq = torch.cat([prompt_ids, resp], dim=1)
        logits = model(seq).logits[0]
        start = prompt_ids.shape[1] - 1            # logits[i] predicts token i+1
        preds = logits[start:start + resp.shape[1]].argmax(-1).tolist()
        return {"argmax": preds}
    raise ValueError(req["op"])


def main():
    tok, model = load()
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((BIND, PORT))
    srv.listen()
    print(f"compute_server ready on {BIND}:{PORT}", flush=True)
    while True:
        conn, _ = srv.accept()
        try:
            while True:
                try:
                    req = json.loads(recv_msg(conn))
                except ConnectionError:
                    break
                send_msg(conn, json.dumps(handle(tok, model, req)).encode())
        finally:
            conn.close()


if __name__ == "__main__":
    main()
