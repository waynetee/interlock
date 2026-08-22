#!/usr/bin/env python3
"""The Pi half of the web demo: a resident client that owns the wire.

WHY THIS EXISTS. demo_e2e.py drives the Pi over SSH -- four `ssh 2a-rpi 'sudo
infcli.py ...'` invocations per run. That is wrong three ways. Each invocation is
a fresh process, so the canonical port is reopened and the 24-probe declared-bucket
bootstrap re-runs every stage. Results come back by regexing JSON out of `infcli
show` on stdout. And it inverts the picture the demo is drawing: the datacenter
reaches into the user's machine as root.

This process instead stays up, holds the port for its whole life (infcli caches it
in `_PORT`, so importing and calling repeatedly is enough), and speaks Socket.IO to
the Spark's orchestrator.

WHAT CROSSES WHICH LINK. The control link carries commands and metadata only --
never a prompt, never a response, never key material. The prompt and the response
cross the certified wire, sealed, and nothing else does. That is what lets the demo
answer "is this staged?" by pointing at the cable: you can tcpdump the control link
and find only JSON envelopes. `_scrub` enforces it on the way out rather than
leaving it to each emit site to remember.

THE PSK NEVER MOVES. It is provisioned out of band at ~/.interlock/psk (root, since
this runs under sudo for AF_PACKET). sync_pi.sh deliberately does not sync it.

Run:  sudo ./venv/bin/python -u pi_agent.py --iface eth0 --spark http://2a-spark:8770
"""
import argparse
import os
import sys
import threading
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import socketio

import infcli
import tok

# The orchestrator serves /agent and /demo; this process is the sole /agent.
NS = "/agent"

# Metadata we are willing to put on the control link. Everything else is dropped:
# an allow-list fails closed when someone adds a field to infcli's log entry.
SAFE_FIELDS = {
    "rid", "nonce", "key_commit", "ct_in", "ct_out", "encrypted",
    "request_audit", "response_audit", "bucket_start", "num_buckets",
    "tau_req_ok", "tau_rsp_ok", "crypto_error",
}


def _scrub(entry):
    """Keep only the fields the UI needs. Ciphertext hex is fine -- it is on the
    cable already -- but ids, text and anything key-shaped are not."""
    out = {k: entry.get(k) for k in SAFE_FIELDS if k in entry}
    for side, field in (("request", "overall_req"), ("response", "overall_rsp")):
        cert = entry.get("%s_cert" % side)
        if not cert:
            continue
        out["%s_cert_len" % side] = len(cert) // 2
        # The digest the CERTIFIER computed -- the epoch root it signed over that
        # period's traffic. The UI labels these "fingerprint", so they have to be
        # the certifier's own values, not a stand-in like KEY_COMMIT that happens
        # to be nearby in the same packet.
        try:
            out["%s_digest" % side] = infcli.parse_cert(infcli.ub(cert))[field].hex()
        except Exception:
            pass
    return out


class Agent:
    def __init__(self, args):
        self.a = self._namespace(args)
        self.sio = socketio.Client(reconnection=True, reconnection_delay=1,
                                   reconnection_delay_max=10)
        # One request in flight, globally. commit.bucket_hash raises on a bucket
        # holding more than one packet -- the combining rule was never pinned
        # against silicon -- and the app only escapes that by keeping a single
        # packet on the wire so each lands alone in its 1 ms bucket. Two
        # concurrent prompts would not race a little, they would throw.
        self.lock = threading.Lock()
        # Warming must be serialised. infcli.canon_port() caches the port, but the
        # check is not atomic: two concurrent warms both see an empty cache, both
        # open a port on the same wire, and the interlock -- which tolerates exactly
        # one packet in flight -- rejects the probes of both. The loser then nulls
        # the cache on its way out and takes the good port with it. Serialising
        # makes the second caller find the first one's port and simply re-report it.
        self.warm_lock = threading.Lock()
        self._wire(args)

    @staticmethod
    def _namespace(args):
        """infcli's functions take the argparse namespace `main` builds. Rebuild it
        here with the same defaults rather than shelling out to infcli."""
        return types.SimpleNamespace(
            iface=args.iface, model=args.model,
            gap_ms=300, wait_ms=15000,
            key=infcli.DEFAULT_KEY,
            challenge_timeout=args.challenge_timeout,
            system="", user_tag="Question:", bot_tag="Answer:")

    # ------------------------------------------------------------------ wiring
    def _wire(self, args):
        sio = self.sio

        @sio.event(namespace=NS)
        def connect():
            print("[agent] connected to %s" % args.spark, flush=True)
            sio.emit("agent:hello", {"iface": args.iface}, namespace=NS)
            # Re-assert the wire's state on every (re)connect, because emitting it
            # once is not enough. The port is warmed as soon as the agent starts,
            # which can finish BEFORE the socket is up -- then ev:warm goes into a
            # namespace that is not connected yet ("emit ev:warm failed: /agent is
            # not a connected namespace"), is dropped, and the server shows a
            # perfectly healthy wire as faulted with Run disabled until someone
            # restarts the agent. Observed after a Spark reboot, which is exactly
            # when the server is slowest to come up. Warming again is cheap (both
            # the port and the tokenizer are cached) and genuinely retries when the
            # first attempt failed, so this doubles as the recovery path.
            threading.Thread(target=_warm, daemon=True).start()

        @sio.event(namespace=NS)
        def disconnect():
            print("[agent] disconnected", flush=True)

        @sio.on("cmd:warm", namespace=NS)
        def _warm(_data=None):
            """Open the port and load the tokenizer before anyone is watching.
            Both are slow exactly once; doing it on the first prompt would put
            the flywheel lock and a tokenizer load inside beat 4.

            This used to let the exception escape. When the board goes quiet --
            which it does a few hours after power-up -- canon_port raises "no sync
            stream", the exception died in this handler thread, and the UI saw the
            agent connected with no fault: Run stayed enabled and failed twelve
            seconds later, in front of the audience. Report it instead, so the
            wire shows as faulted before anyone can press anything."""
            t0 = time.time()
            try:
                with self.warm_lock:
                    infcli.canon_port(self.a)
                    tok.tokenizer()
            except Exception as e:
                # Drop the cached half-open port so the next warm genuinely retries
                # rather than handing back a dead object.
                infcli._PORT["p"] = None
                msg = "%s: %s" % (type(e).__name__, e)
                print("[agent] warm FAILED: %s" % msg, flush=True)
                self.emit("ev:wire_fault", {"error": msg})
                return
            self.emit("ev:warm", {"secs": round(time.time() - t0, 1)})

        @sio.on("cmd:prompt", namespace=NS)
        def _prompt(data):
            threading.Thread(target=self._do_prompt, args=(data,),
                             daemon=True).start()

        @sio.on("cmd:challenge", namespace=NS)
        def _challenge(data):
            threading.Thread(target=self._do_challenge, args=(data,),
                             daemon=True).start()

    def emit(self, ev, payload):
        try:
            self.sio.emit(ev, payload, namespace=NS)
        except Exception as e:                      # a dead UI must not kill the wire
            print("[agent] emit %s failed: %s" % (ev, e), flush=True)

    # ------------------------------------------------------------------ actions
    def _do_prompt(self, data):
        text = data.get("text") or ""
        if not self.lock.acquire(blocking=False):
            self.emit("ev:busy", {"stage": "prompt"})
            return
        try:
            t0 = time.time()
            ids = tok.encode_ids(text)
            # The token COUNT is metadata; the ids are not -- they are the prompt.
            self.emit("ev:tokenized", {"n_tokens": len(ids),
                                       "payload_bytes": 4 * len(ids),
                                       "secs": round(time.time() - t0, 2)})

            t1 = time.time()
            entry = infcli.send_tokens(self.a, ids)
            info = _scrub(entry)
            info["secs"] = round(time.time() - t1, 2)
            self.emit("ev:sent", info)

            rsp_ids = entry.get("response_ids")
            if entry.get("crypto_error"):
                self.emit("ev:opened", {"rid": entry["rid"], "ok": False,
                                        "error": entry["crypto_error"]})
                return
            # No response at all is a FAILURE, not an empty success. Reporting
            # ok=True with zero tokens paints a blank answer and then a verdict
            # built from nothing. The usual cause is being on the wrong port --
            # the client half only receives on the certified client link -- so
            # say that rather than showing an empty box.
            if not rsp_ids:
                self.emit("ev:opened", {
                    "rid": entry["rid"], "ok": False,
                    "error": "no response returned. Certificates: request=%s "
                             "response=%s. If both are missing, this host is "
                             "probably on the compute port -- the client belongs "
                             "on J30." % (entry.get("request_audit"),
                                          entry.get("response_audit"))})
                return
            # The decrypted text is the demo's output and the one plaintext the UI
            # is entitled to. It is emitted from HERE, by the holder of the key,
            # which is the point being made -- the Spark cannot show it on the
            # Pi's behalf.
            out = tok.decode_ids(rsp_ids) if rsp_ids else ""
            self.emit("ev:opened", {"rid": entry["rid"], "ok": True,
                                    "n_tokens": len(rsp_ids or []), "text": out})
        except Exception as e:
            self.emit("ev:error", {"stage": "prompt",
                                   "error": "%s: %s" % (type(e).__name__, e)})
            print("[agent] prompt failed: %s: %s" % (type(e).__name__, e), flush=True)
        finally:
            self.lock.release()

    def _do_challenge(self, data):
        rid = int(data.get("rid", 0))
        if not self.lock.acquire(blocking=False):
            self.emit("ev:busy", {"stage": "challenge"})
            return
        try:
            t0 = time.time()
            # do_challenge streams the prover's own status lines as they arrive in
            # band. Forwarding them straight through is what makes the UI's proof
            # progress real rather than a timer pretending to be one.
            res = infcli.do_challenge(
                self.a, rid,
                lambda s: self.emit("ev:proof_status", {"rid": rid, "line": s}))
            self.emit("ev:proof_result", {"rid": rid, "result": res,
                                          "secs": round(time.time() - t0, 1)})
        except Exception as e:
            self.emit("ev:error", {"stage": "challenge",
                                   "error": "%s: %s" % (type(e).__name__, e)})
            print("[agent] challenge failed: %s: %s" % (type(e).__name__, e), flush=True)
        finally:
            self.lock.release()

    def run(self, url):
        while True:
            try:
                self.sio.connect(url, namespaces=[NS], transports=["websocket"])
                self.sio.wait()
            except Exception as e:
                print("[agent] connect failed (%s); retrying in 3s" % e, flush=True)
                time.sleep(3)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--iface", default="eth0")
    ap.add_argument("--spark", default=os.environ.get("SPARK_URL",
                                                      "http://2a-spark:8770"))
    # Only infcli's own transformers path uses --model, which this agent never
    # takes; tok.py finds its tokenizer at app/tokenizer/tinyllama (TOKENIZER_DIR
    # overrides). Kept so infcli's namespace is complete.
    ap.add_argument("--model", default="")
    # infcli's own default is 1800 s, sized for a full-soundness proof on a big
    # model. Here fast mode returns in ~15 s and sound in ~110 s, so 1800 just
    # means a dead wire hangs the demo for half an hour. demo_server's watchdog
    # gives up before this does; this is the backstop under it.
    ap.add_argument("--challenge-timeout", type=int, default=600)
    a = ap.parse_args()
    if os.geteuid() != 0:
        sys.exit("pi_agent needs root for AF_PACKET on %s" % a.iface)
    print("[agent] starting; wire=%s spark=%s" % (a.iface, a.spark), flush=True)
    Agent(a).run(a.spark)


if __name__ == "__main__":
    main()
