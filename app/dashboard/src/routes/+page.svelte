<script lang="ts">
	/**
	 * Interlock — the case.
	 *
	 * Driven by demo_server.py (interlock/app), which orchestrates a Raspberry Pi
	 * holding the certified wire and a Spark running the model behind a PolarFire
	 * FPGA that fingerprints every packet in both directions. Every value rendered
	 * here arrived over that wire. The only thing this file invents is the pacing.
	 *
	 * ...unless the board is off, in which case it invents everything — see
	 * `simulate()`. That path exists so the demo survives a dead board, and it says
	 * so on screen in a strip that is never dismissible, because a rehearsal that
	 * cannot be told apart from a run is worse than no rehearsal.
	 *
	 * WHO IS READING THIS. A panel in the lid of a case, seen standing up from a few
	 * feet by someone who has not been briefed. One screen, no scroll, and nothing
	 * static: no title, no headings, no explainer copy. The picture IS the
	 * explanation — the question itself rides the cable, seals into its real
	 * ciphertext bytes and opens again; the certifier stamps a fingerprint out of
	 * each passing packet and RACKS IT INSIDE ITS OWN BODY; only when the proof
	 * begins do the films slide into the GPU cluster and combine there, beside the
	 * model's own commitment, because that is where the proof actually runs. The
	 * numbers an engineer wants are on the console and in /lab.
	 */
	import {
		build,
		stencil,
		strips,
		DEFAULT_FACE,
		DEFAULT_GRID,
		DEFAULT_WORD
	} from '$lib/fingerprint-shares';
	import { cn } from '$lib/utils';
	import { resolve } from '$app/paths';
	import { io, type Socket } from 'socket.io-client';
	import { scale } from 'svelte/transition';
	import { onDestroy, onMount } from 'svelte';

	type Verdict = { verdict: string; U: string; verify: string; keybind: string };

	let socket: Socket | undefined;
	let connected = $state(false);
	let agentUp = $state(false);
	let wireOk = $state(false);
	let wireFault = $state('');
	/** the server's own mode label, kept verbatim for the console and the tooltip */
	let modeRaw = $state('');
	let busy = $state(false);

	/** the tamper switch: sticky, and only the operator flips it */
	let armed = $state(false);
	/** and whether the run being shown was actually the tampered one */
	let tampered = $state(false);
	/** force the simulator even with a healthy board */
	let simForce = $state(false);
	/** whether the run being shown came out of `simulate()` rather than the wire */
	let simRun = $state(false);

	let caption = $state('Ready — press PROMPT to send a question.');
	let phase = $state<'idle' | 'req' | 'gen' | 'rsp' | 'prove' | 'done'>('idle');
	let hotFpga = $state(false);
	let hotSpark = $state(false);

	/**
	 * Where the payload is, along the cable: your machine, the certifier, the mouth
	 * of the GPU cluster. The payload is the TEXT — the question and later the
	 * answer ride the wire themselves, scrambling into their real ciphertext bytes
	 * at the moment they are sealed and back at the moment they are opened.
	 */
	// One y for the whole journey: the card rides the cable's height everywhere,
	// including inside the cluster -- it moves left to right and never bobs.
	const STOP = [
		{ x: 19, y: 41 },
		{ x: 39, y: 41 },
		{ x: 81.5, y: 41 }
	];
	let pktX = $state(STOP[0]);
	let pktText = $state('');
	let pktSealed = $state(false);
	let pktShown = $state(false);

	let reqFp = $state<string | null>(null);
	let rspFp = $state<string | null>(null);
	let modelFp = $state<string | null>(null);
	/**
	 * The two fingerprints the certifier mints, as FILMS carrying the strip's own
	 * cell pattern. Each is stamped as the packet passes and then HELD inside the
	 * certifier — the input film through generation, both films through delivery —
	 * because until the proof runs, the certifier is the only party holding them.
	 * When the proof begins they slide together into the GPU cluster (the proof
	 * runs on the Spark, not in the cable) and are absorbed into the register.
	 * 'held' is racked inside the certifier; 'docked' is arrived over the
	 * register; 'gone' is absorbed into it (the register then shows the strip).
	 */
	type Chip = 'hidden' | 'held' | 'drop' | 'run' | 'docked' | 'gone';
	let chipA = $state<Chip>('hidden');
	let chipB = $state<Chip>('hidden');
	/** the model's own commitment is revealed in the cluster when the proof begins */
	let modelShown = $state(false);
	/** the proof is in flight: the register hunts for the seat until this clears */
	let proving = $state(false);
	/** when the hunt began: the verdict must let it run ~3s before settling */
	let proveT0 = 0;
	let promptText = $state('');
	let answer = $state('');
	let verdict = $state<Verdict | null>(null);
	/** a run that died: the server's own words, shown until the next run starts */
	let runFault = $state('');

	const short = (h: string | null, n = 8) => (h ? h.slice(0, n).toUpperCase() : '—');
	/** the run's narration, on the console rather than on the lid */
	const log = (s: string) => console.debug('[interlock]', s);

	let pending: Record<string, any> = {};
	let chain: Promise<unknown> = Promise.resolve();
	let generation = 0;
	const queue = (fn: () => Promise<void>) => (chain = chain.then(fn).catch(console.error));

	/** Sleep that resolves to false if a newer run started while we waited. */
	async function step(ms: number, gen: number) {
		await new Promise((r) => setTimeout(r, ms));
		return gen === generation;
	}

	const frozen = () =>
		typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

	// ── the seal/open animation ────────────────────────────────────────────────
	/**
	 * The payload text boiling into different bytes, one character at a time behind
	 * a scanning head. The cipher form is the run's REAL ciphertext (ct_in/ct_out
	 * off the wire), not decoration — what appears on the cable is a window onto
	 * the bytes that actually crossed it.
	 */
	let scrRaf = 0;
	const HEXCHARS = '0123456789ABCDEF';
	function scrambleTo(target: string, ms = 650) {
		cancelAnimationFrame(scrRaf);
		if (frozen()) {
			pktText = target;
			return;
		}
		const from = pktText;
		const n = Math.max(from.length, target.length);
		const t0 = performance.now();
		const tick = (now: number) => {
			const k = Math.min(1, (now - t0) / ms);
			const head = Math.floor(k * n);
			let s = '';
			for (let i = 0; i < n; i++) {
				if (i < head) s += target[i] ?? '';
				else if (i < head + 3) s += HEXCHARS[(Math.random() * 16) | 0];
				else s += from[i] ?? '';
			}
			pktText = s;
			if (k < 1) scrRaf = requestAnimationFrame(tick);
			else pktText = target;
		};
		scrRaf = requestAnimationFrame(tick);
	}

	/** the payload's ciphertext, cut to the same length so the chip holds its shape */
	function cipherOf(hex: string | undefined, n: number) {
		let h = (hex || '').toUpperCase().replace(/[^0-9A-F]/g, '');
		if (!h) h = 'A7F03C9E5B21D48C6E90F17B24A8D35E';
		while (h.length < n) h += h;
		return '0x' + h.slice(0, Math.max(10, n));
	}

	/** the card wraps now, so the ceiling is about keeping it a card, not a page */
	const clip = (s: string, n = 120) => (s.length > n ? s.slice(0, n - 1) + '…' : s);

	/** Everything a run puts on the screen. The switches are not part of a run. */
	function clearRun() {
		phase = 'idle';
		caption = 'Ready — press PROMPT to send a question.';
		hotFpga = hotSpark = false;
		pktShown = pktSealed = false;
		pktX = STOP[0];
		pktText = '';
		cancelAnimationFrame(scrRaf);
		reqFp = rspFp = null;
		chipA = chipB = 'hidden';
		modelShown = false;
		proving = false;
		proveT0 = 0;
		runFault = '';
		promptText = '';
		answer = '';
		verdict = null;
		tampered = false;
		simRun = false;
		busy = false;
	}

	/** the Reset button: the run, the switches, and anything armed on the server */
	function resetAll() {
		generation += 1; // orphans an in-flight animation, simulated or not
		chain = Promise.resolve();
		clearRun();
		armed = false;
		socket?.emit('demo:reset');
	}

	async function runRequest(d: any, gen: number) {
		phase = 'req';
		pktSealed = false;
		pktX = STOP[0];
		pktText = asked || promptText;
		pktShown = true;
		caption = 'A question leaves your machine.';
		if (!(await step(800, gen))) return;

		pktSealed = true;
		scrambleTo(cipherOf(d.ct_in, pktText.length));
		caption = 'It is encrypted before it touches the cable.';
		log(`SEAL   ${d.n_tokens} tok → ${(d.ct_in ?? '').length / 2}B`);
		if (!(await step(1000, gen))) return;

		pktX = STOP[1];
		hotFpga = true;
		if (!(await step(950, gen))) return;
		reqFp = d.request_digest ?? null;
		// the film drops into the certifier's lower slot and STAYS there: traffic
		// moves on, the evidence does not
		chipA = 'held';
		caption = 'The certifier stamps a fingerprint off the sealed bytes and keeps it.';
		log(`CERT   inbound  ${short(reqFp, 16)} audit=${d.request_audit ? 'PASS' : 'FAIL'}`);
		if (!(await step(frozen() ? 30 : 1100, gen))) return;

		pktX = STOP[2];
		hotFpga = false;
		hotSpark = true;
		if (!(await step(950, gen))) return;
		pktShown = false;
	}

	async function runResponse(d: any, text: string, gen: number) {
		// The answer exists in the clear HERE first: the cluster generates it,
		// and only then does it get encrypted for the trip back. Showing that is
		// honest -- the datacenter necessarily holds the plaintext it produced --
		// and it is the beat that makes "encrypted on the wire" legible: you see
		// the words exist, then boil into bytes, then travel.
		phase = 'gen';
		pktSealed = false;
		pktText = '';
		pktX = STOP[2];
		pktShown = true;
		caption = 'The GPU cluster generates the answer…';
		scrambleTo(clip(text), 900);
		if (!(await step(1500, gen))) return;

		pktSealed = true;
		scrambleTo(cipherOf(d.ct_out, clip(text).length));
		caption = '…and encrypts it for the trip back.';
		if (!(await step(1100, gen))) return;

		phase = 'rsp';
		pktX = STOP[1];
		hotSpark = false;
		hotFpga = true;
		if (!(await step(950, gen))) return;

		rspFp = d.response_digest ?? null;
		// second film racks above the first: the certifier now holds both
		chipB = 'held';
		caption = 'The answer is fingerprinted on the way out — the certifier holds both.';
		log(`CERT   outbound ${short(rspFp, 16)} audit=${d.response_audit ? 'PASS' : 'FAIL'}`);
		if (!(await step(frozen() ? 30 : 1100, gen))) return;

		pktX = STOP[0];
		hotFpga = false;
		if (!(await step(950, gen))) return;
		pktSealed = false;
		scrambleTo(clip(text));
		caption = 'Only your machine holds the key that opens it.';
		if (!(await step(1000, gen))) return;
		// the opened answer STAYS parked at your machine through the proof --
		// delivery is a state the storyboard keeps on screen, not a flash
		answer = text;
		log(`OPEN   ${text}`);
	}

	async function runProve(gen: number) {
		phase = 'prove';
		hotSpark = true;
		// beat one: the cluster shows its hand -- the commitment to the model it
		// promised to run, fixed before anything was sent
		modelShown = true;
		caption = 'The cluster reveals the fingerprint of the model it promised to run.';
		if (!(await step(frozen() ? 30 : 1300, gen))) return;

		// beat two: the certifier releases both films and they ride the U --
		// down through its floor, along the trench, up into the cluster from
		// below. The proof that combines them runs on the Spark, so that is
		// where they go. Output leads, input trails a beat behind, so the pair
		// reads as a conveyor rather than a swap.
		caption = 'The certifier sends its two fingerprints into the cluster.';
		const t = (ms: number) => step(frozen() ? 30 : ms, gen);
		// The two films share one trench, so the spacing is temporal: the input
		// film only enters the run once the output film is more than a film's
		// width ahead, and they never overlap until the moment they combine.
		chipB = 'drop';
		if (!(await t(650))) return;
		chipB = 'run';
		if (!(await t(100))) return;
		chipA = 'drop';
		if (!(await t(650))) return;
		chipA = 'run';
		if (!(await t(400))) return;
		chipB = 'docked';
		if (!(await t(800))) return;
		// the moment a film lands it is absorbed and the sliding is already
		// running: travel and hunt are one continuous motion, with no pause
		// between them. `proving` stays up until the verdict lands however long
		// that takes -- the animation is paced by the prover, not a timer.
		chipB = 'gone';
		proving = true;
		proveT0 = performance.now();
		caption = 'Now it has to prove all three came from the promised model.';
		if (!(await t(100))) return;
		chipA = 'docked';
		if (!(await t(800))) return;
		chipA = 'gone';
	}

	async function runVerdict(d: any, gen: number) {
		// A verdict for a run that has already been superseded -- Reset pressed, or a
		// second Prompt -- must not repaint the panel it is no longer about.
		if (gen !== generation) return;
		// the sliding is the drama: even when the prover has already ruled, the
		// sheets get their ~3 seconds of hunting before the word is allowed to
		// develop
		if (proving && proveT0 && !frozen()) {
			const left = 3000 - (performance.now() - proveT0);
			if (left > 0 && !(await step(left, gen))) return;
		}
		verdict = d.result as Verdict;
		phase = 'done';
		proving = false;
		hotSpark = false;
		const ok = verdict?.verdict === 'PASS';
		caption = ok
			? 'It did. The three fingerprints line up.'
			: 'It could not. That answer never went past the certifier.';
		log(`PROOF  ${verdict?.verdict}  verify=${verdict?.verify}  binding=${verdict?.keybind}`);
		busy = false;
	}

	onMount(() => {
		socket = io('/demo', { transports: ['websocket'] });
		socket.on('connect', () => (connected = true));
		socket.on('disconnect', () => (connected = false));
		socket.on('hello', (d: any) => {
			agentUp = !!d.agent;
			wireOk = !!d.wire;
			if (d.mode) modeRaw = d.mode;
			if (d.prompt) SIM_PROMPT = d.prompt;
			if (d.model_fp) modelFp = d.model_fp;
		});
		socket.on('wire:agent', (d: any) => {
			agentUp = !!d.up;
			if (!d.up) wireOk = false;
		});
		socket.on('wire:ready', () => {
			wireOk = true;
			wireFault = '';
		});
		// The board goes quiet a few hours after power-up. The strip says so, and the
		// simulator picks itself up, so nobody presses PROMPT and finds out twelve
		// seconds later in front of an audience.
		socket.on('wire:fault', (d: any) => {
			wireOk = false;
			wireFault = d?.error ?? 'no sync stream';
			log(`FAULT  ${wireFault}`);
		});
		socket.on('beat:armed', () => (tampered = true));
		socket.on('beat:reset', clearRun);
		socket.on('beat:start', (d: any) => {
			generation += 1; // orphans any in-flight animation from a previous run
			chain = Promise.resolve();
			clearRun();
			// The server says beat:armed BEFORE beat:start, so the clear above just
			// ate it. The switch state is this client's own request, so it is the
			// truth about the run it just launched.
			tampered = armed;
			promptText = d?.prompt ?? '';
			busy = true;
		});
		socket.on('beat:tokenized', (d: any) => (pending = { ...pending, ...d }));
		socket.on('beat:certified', (d: any) => (pending = { ...pending, ...d }));
		socket.on('beat:answer', (d: any) => {
			const gen = generation;
			queue(async () => {
				if (gen !== generation) return;
				await runRequest(pending, gen);
				await runResponse(pending, d.ok ? d.text : 'could not open it', gen);
				// a run that failed to open has no proof coming: the server's
				// beat:error follows, and 'proving' would wait on it forever
				if (d.ok) await runProve(gen);
			});
		});
		socket.on('beat:verdict', (d: any) => {
			if (d.model_fp) modelFp = d.model_fp;
			const gen = generation;
			queue(() => runVerdict(d, gen));
		});
		socket.on('beat:proof_status', (d: any) => log(`PROVE  ${String(d.line).trim()}`));
		// A run that dies must SAY so. This used to write a caption that no longer
		// renders, which read as "I pressed PROMPT and nothing happened" -- the
		// worst possible answer. The banner strip carries it now.
		socket.on('wire:busy', () => {
			runFault =
				'the wire is still finishing the previous run — give it a moment and press PROMPT again, or press RESET';
			log('BUSY   run refused: previous run still holds the wire');
		});
		socket.on('beat:error', (d: any) => {
			runFault = d.error ?? 'something went wrong on the wire — press PROMPT to try again';
			log(`ERROR  ${d.error ?? ''}`);
			proving = false;
			busy = false;
			// A halt that did not take leaves the machine up, so the panel comes back
			// rather than sitting behind a "powering off" curtain that will never lift.
			goingDown = false;
		});
		socket.on('beat:shutdown', () => (goingDown = true));
	});
	onDestroy(() => socket?.disconnect());

	// ── running it ─────────────────────────────────────────────────────────────
	/** the wire is only live when all three of these hold */
	const liveWire = $derived(connected && agentUp && wireOk);
	const simMode = $derived(simForce || !liveWire);

	function start() {
		if (busy || goingDown) return;
		if (simMode) {
			simulate(armed);
			return;
		}
		socket?.emit('demo:reset');
		setTimeout(() => socket?.emit(armed ? 'demo:tamper' : 'demo:run', {}), 250);
	}

	// ── the simulator ──────────────────────────────────────────────────────────
	/**
	 * A run with no hardware in it.
	 *
	 * The board goes quiet a few hours after power-up and the Pi has to be on the
	 * Spark's AP, so there are plenty of ways to open the case and find nothing on
	 * the wire. This drives the same four beat functions the socket drives, on the
	 * same pacing, so what is rehearsed is what will run -- and it fabricates its
	 * digests rather than replaying a captured pair, because a recording of a real
	 * run is exactly the thing that could be passed off as one.
	 */
	/**
	 * The question the simulator asks, and the answer it invents. Both are only a
	 * FALLBACK: a connected server sends its own PROMPT in `hello` and that wins.
	 * Two copies of one string drift the moment somebody sets PROMPT in the
	 * environment, and the copy that drifts is the one on screen when the board is
	 * dead -- which is exactly when nobody can check it against a real run.
	 */
	let SIM_PROMPT = $state('Question: What does IAEA stand for?\nAnswer:');
	const SIM_ANSWER = 'The International Atomic Energy Agency';
	const SIM_STATUS = [
		'loading proving key',
		'committing to the token layer',
		'weld: binding ciphertext to the proven tokens',
		'B1/B2 key binding at full strength',
		'folding'
	];

	/**
	 * Forty hex characters that behave like a digest: dependent on everything handed
	 * in, and different every run. FNV-1a into xorshift32 -- crypto.subtle is not
	 * available here, the demo being served over plain http on a LAN address, and
	 * this has no security job to do anyway.
	 */
	function fauxDigest(s: string) {
		let h = 0x811c9dc5 >>> 0;
		for (let i = 0; i < s.length; i++) {
			h ^= s.charCodeAt(i);
			h = Math.imul(h, 0x01000193) >>> 0;
		}
		let out = '';
		for (let i = 0; i < 40; i++) {
			h ^= h << 13;
			h >>>= 0;
			h ^= h >>> 17;
			h ^= h << 5;
			h >>>= 0;
			out += '0123456789abcdef'[h & 15];
		}
		return out;
	}

	function simulate(tamper: boolean) {
		generation += 1;
		const gen = generation;
		chain = Promise.resolve();
		clearRun();
		busy = true;
		simRun = true;
		tampered = tamper;
		promptText = SIM_PROMPT;
		if (!modelFp) modelFp = fauxDigest('simulated-weights');

		const nonce = `${Date.now()}:${Math.random()}`;
		const d = {
			n_tokens: 11,
			ct_in: fauxDigest(`ct_in:${nonce}`) + fauxDigest(`ct_in2:${nonce}`),
			ct_out: fauxDigest(`ct_out:${nonce}`) + fauxDigest(`ct_out2:${nonce}`),
			request_digest: fauxDigest(`in:${SIM_PROMPT}:${nonce}`),
			response_digest: fauxDigest(`out:${SIM_ANSWER}:${nonce}`),
			request_audit: true,
			response_audit: true
		};

		queue(async () => {
			if (gen !== generation) return;
			log('SIM    simulated board — nothing below was certified or proven');
			await runRequest(d, gen);
			await runResponse(d, SIM_ANSWER, gen);
			await runProve(gen);
			for (const line of SIM_STATUS) {
				if (!(await step(1150, gen))) return;
				log(`PROVE  ${line}`);
			}
			if (!(await step(900, gen))) return;
			await runVerdict(
				{
					result: tamper
						? { verdict: 'FAIL', U: '2^-40', verify: 'REJECT', keybind: 'MISMATCH' }
						: { verdict: 'PASS', U: '2^-40', verify: 'ACCEPT', keybind: 'OK' },
					secs: 24.6
				},
				gen
			);
		});
	}

	// ── power ──────────────────────────────────────────────────────────────────
	/**
	 * Two presses, and the second one only counts inside four seconds. This kills the
	 * Pi and then the Spark -- including the server that is serving this page, so
	 * there is no undo and no way back except opening the case.
	 */
	let armDown = $state(false);
	let downTimer = 0;
	let goingDown = $state(false);

	function shutdown() {
		// A dead link must refuse, not pretend: pressing this with the socket
		// down used to arm, confirm, paint the "Powering off" curtain -- and
		// emit into nothing, leaving two healthy machines behind a black
		// screen that said otherwise.
		if (!connected) {
			log('SHUTDOWN ignored: no link to the orchestrator');
			return;
		}
		if (!armDown) {
			armDown = true;
			clearTimeout(downTimer);
			downTimer = window.setTimeout(() => (armDown = false), 4000);
			return;
		}
		clearTimeout(downTimer);
		armDown = false;
		// goingDown is set by beat:shutdown -- the server's own acknowledgement
		// -- never optimistically here, so the curtain only falls when the
		// order has actually been received.
		// The token is checked server-side, so a stray `demo:shutdown` from a console
		// or a replayed frame cannot power the rack off by itself.
		socket?.emit('demo:shutdown', { confirm: 'POWER OFF' });
	}

	// ── the combine ────────────────────────────────────────────────────────────
	// What the cluster actually HOLDS, as opposed to what exists somewhere on the
	// stage: the model commitment once the proof reveals it, and the certifier's
	// two films only once they have landed. The stack reads these, so nothing
	// shows up inside the cluster before the storyboard says it arrived.
	const regReq = $derived(chipA === 'gone' ? reqFp : null);
	const regRsp = $derived(chipB === 'gone' ? rspFp : null);
	const regModel = $derived(modelShown ? modelFp : null);

	// ── the strip that is never dismissible when it matters ────────────────────
	/**
	 * What an audience has a right to know before they believe the screen. The
	 * simulator outranks the tamper because "none of this happened" is the more
	 * important of the two. A live, honest run has nothing to disclaim, so the
	 * strip only exists when one of the warnings holds; the server's own mode
	 * label rides as the stage tooltip for whoever is running the demo.
	 */
	const banner = $derived(
		runFault
			? { tag: 'Fault', tone: 'fault' as const, say: runFault }
			: tampered
				? {
						tag: 'Tampered',
						tone: 'fault' as const,
						say: 'the cluster is claiming an answer the certifier never saw — this fails every time'
					}
				: null
	);

	/**
	 * The prompt without its scaffolding, so the payoff reads as a question. A
	 * few-shot prompt carries worked examples in front; the question being asked
	 * is the LAST one, so take the text after the final "Question:".
	 */
	const asked = $derived(
		(promptText.split(/Question:/i).pop() ?? '')
			.replace(/\s*Answer:\s*$/i, '')
			.trim()
	);
	/** the far end is doing something you cannot see: say so with a sweep, not a word */
	const working = $derived(phase === 'gen' || phase === 'prove');
	/** and your own machine lights up for the two moments the key is in use —
	 * not for the whole time the delivered answer sits parked there */
	const hotHome = $derived(pktShown && pktX === STOP[0] && (phase === 'req' || phase === 'rsp'));
	const TONE = {
		caution: { bar: 'border-l-caution', text: 'text-caution' },
		fault: { bar: 'border-l-fault', text: 'text-fault' }
	};

	// ── the flying films: geometry and dressing ────────────────────────────────
	// Stage coordinates for a film's journey: racked inside the certifier's tall
	// body while it holds them (input in the lower slot, output stacked above it,
	// the way the storyboard stacks them), then a long slide right into the
	// cluster at prove time, where the register absorbs them. C never travels —
	// the model commitment lives in the cluster and is simply revealed there.
	// A film's journey is a U: racked inside the certifier (input low, output
	// above -- the way the storyboard stacks them), then out through the
	// certifier's floor, along the trench under the stage, and up into the
	// cluster from below, where the register absorbs it beside the model
	// commitment. Each leg is its own state so the corners are real corners.
	// A film with its label runs ~10% of stage height; slots and docks are
	// spaced ~11.5% so the stack never collides with itself.
	// The mint slot sits RIGHT UNDER the cable, where the passing payload is:
	// each film pops out directly beneath the packet it was stamped from. The
	// input film takes that slot on the request pass; when the output film pops
	// out on the return pass it takes the slot itself, pushing the input film
	// down a rack.
	const SLOT_FRESH = { x: 39, y: 56.5 };
	const SLOT_PUSHED = { x: 39, y: 74 };
	const CHIP_B = {
		held: SLOT_FRESH,
		drop: { x: 39, y: 92 },
		run: { x: 81.5, y: 92 },
		dock: { x: 81.5, y: 37 }
	};
	const CHIP_A = $derived({
		held: chipB === 'hidden' ? SLOT_FRESH : SLOT_PUSHED,
		drop: { x: 39, y: 92 },
		run: { x: 81.5, y: 92 },
		dock: { x: 81.5, y: 47 }
	});
	// Three shades of one green, the way the printed cards ink them: the input
	// film lightest, the output deeper, the model commitment deepest — the same
	// family so the stack reads as one instrument, stepped so the three strips
	// stay tellable apart. (The print inks are darker; these are the same
	// ordering rebalanced for a dark panel.)
	const HUEA = '#9ad161';
	const HUEB = '#7cc055';
	const HUEC = '#5fae4c';
	/** one width for a film everywhere it appears, so landing IS combining --
	 * nothing resizes between the flight and the stack */
	const FILMW = 'clamp(180px,24vw,440px)';
	const failB = $derived(!!verdict && verdict.verdict !== 'PASS');
	// The films' own cell patterns — the same strips the register is composing,
	// derived from the same digests, so what flies is what lands.
	const filmMask = stencil(DEFAULT_WORD, DEFAULT_FACE, DEFAULT_GRID);
	const filmShares = $derived(build(reqFp ?? '', rspFp ?? '', modelFp ?? '', !failB, filmMask));
	const filmStrips = $derived(strips(filmShares, DEFAULT_GRID, 2, modelFp ?? '', 0.5));
	const clusterStatus = $derived(
		verdict
			? verdict.verdict === 'PASS'
				? 'verified'
				: 'rejected'
			: proving
				? 'aligning the fingerprints…'
				: phase === 'gen'
					? 'running the model'
					: modelShown
						? 'model commitment on file'
						: ''
	);
</script>

{#snippet toggle(on: boolean, label: string, tone: 'fault' | 'caution', click: () => void)}
	<button
		type="button"
		role="switch"
		aria-checked={on}
		aria-label={label}
		onclick={click}
		disabled={goingDown}
		class="flex items-center gap-2.5 disabled:pointer-events-none disabled:opacity-35"
	>
		<span
			class={cn(
				'relative h-[1.5em] w-[2.9em] border text-[clamp(0.7rem,0.85vw,1rem)] transition-colors duration-200',
				on
					? tone === 'fault'
						? 'border-fault bg-fault/20'
						: 'border-caution bg-caution/20'
					: 'border-border bg-muted'
			)}
		>
			<span
				class={cn(
					'absolute top-[0.13em] size-[1.2em] transition-all duration-200',
					on
						? `left-[1.57em] ${tone === 'fault' ? 'bg-fault' : 'bg-caution'}`
						: 'left-[0.13em] bg-muted-foreground/70'
				)}
			></span>
		</span>
		<span
			class={cn(
				't-tag font-mono uppercase transition-colors',
				on
					? tone === 'fault'
						? 'text-fault'
						: 'text-caution'
					: 'text-muted-foreground hover:text-foreground'
			)}
		>
			{label}
		</span>
	</button>
{/snippet}

{#snippet filmchip(
	idx: number,
	role: string,
	hex: string | null,
	hue: string,
	state: Chip,
	pos: Record<'held' | 'drop' | 'run' | 'dock', { x: number; y: number }>,
	bad: boolean
)}
	{@const at = pos[state === 'hidden' ? 'held' : state === 'docked' || state === 'gone' ? 'dock' : state]}
	{@const ink = bad ? 'var(--fault)' : hue}
	{@const rows = filmStrips.heights[idx]}
	<div
		class={cn(
			'absolute z-20 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-0.5 transition-all duration-[1100ms] ease-in-out motion-reduce:transition-none',
			state === 'hidden' && 'scale-75 opacity-0',
			state === 'held' && 'opacity-100 duration-[420ms]',
			// the U, leg by leg: ease into the drop, run the trench flat-out,
			// ease off rising into the cluster
			state === 'drop' && 'opacity-100 duration-[600ms] ease-in',
			state === 'run' && 'opacity-100 duration-[1000ms] ease-linear',
			state === 'docked' && 'opacity-100 duration-[800ms] ease-out',
			state === 'gone' && 'opacity-0 duration-[400ms]'
		)}
		style="left:{at.x}%;top:{at.y}%;width:{FILMW}"
	>
		<!-- the name rides along until the film reaches the stack: from there the
		     strips overlap on purpose, and three labels in one place is scribble -->
		<span
			class={cn(
				'font-mono text-[clamp(0.72rem,0.85vw,1.05rem)] whitespace-nowrap uppercase transition-opacity duration-300',
				(state === 'docked' || state === 'gone') && 'opacity-0'
			)}
			style="color:{ink}">{role} · {hex ? '0x' + short(hex, 8) : '—'}</span
		>
		<!-- the strip's actual cells: what flies is what the register composes -->
		<svg
			viewBox="0 0 {DEFAULT_GRID.cols} {rows}"
			class="w-full"
			preserveAspectRatio="none"
			aria-hidden="true"
		>
			{#each { length: rows } as _r, r (r)}
				{#each { length: DEFAULT_GRID.cols } as _c, c (c)}
					{#if filmStrips.cells[idx][r * DEFAULT_GRID.cols + c] > 0}
						<rect x={c} y={r} width="1.05" height="1.05" fill={ink} />
					{/if}
				{/each}
			{/each}
		</svg>
	</div>
{/snippet}

<div class="flex h-svh flex-col overflow-hidden bg-background text-foreground">
	<main class="flex min-h-0 flex-1 flex-col gap-[clamp(0.5rem,1.4vh,1.1rem)] px-6 py-[1.2vh]">
		<!-- controls only: everything else on this screen is a live value -->
		<div class="flex shrink-0 flex-wrap items-center justify-between gap-x-8 gap-y-3">
			<div class="flex flex-wrap items-center gap-x-6 gap-y-3">
				{@render toggle(armed, 'Tamper', 'fault', () => (armed = !armed))}
				{@render toggle(simForce || !liveWire, 'Simulate', 'caution', () => {
					// off is only offerable when there is a wire to fall back to
					if (liveWire) simForce = !simForce;
				})}
			</div>
			<div class="flex flex-wrap items-center gap-x-4 gap-y-3">
				<a
					href={resolve('/lab')}
					class="font-mono text-[10px] tracking-[0.16em] text-muted-foreground/40 uppercase hover:text-foreground"
					>bench</a
				>
				<button
					class={cn(
						't-tag border px-3 py-1 font-mono uppercase transition-colors',
						armDown
							? 'border-fault bg-fault/20 text-fault'
							: 'border-border text-muted-foreground/60 hover:border-fault hover:text-fault'
					)}
					disabled={goingDown || !connected}
					onclick={shutdown}
				>
					{armDown ? 'press again to power off' : connected ? 'shut down' : 'no link'}
				</button>
				<button
					class="t-tag border border-border px-4 py-2 font-mono text-muted-foreground uppercase transition-colors hover:text-foreground disabled:pointer-events-none disabled:opacity-35"
					disabled={goingDown}
					onclick={resetAll}>Reset</button
				>
				<button
					class={cn(
						't-lead border border-signal bg-signal/10 px-8 py-2 font-mono tracking-[0.14em] text-signal uppercase transition-colors hover:bg-signal/20 disabled:pointer-events-none disabled:opacity-35',
						!busy && !goingDown && phase !== 'done' && 'ilk-breathe'
					)}
					disabled={busy || goingDown}
					onclick={start}>Prompt</button
				>
			</div>
		</div>

		<!-- only exists while there is something to disclaim -->
		{#if banner}
			<div
				class={cn(
					't-body flex shrink-0 flex-wrap items-baseline gap-x-3 border-l-4 bg-card/60 px-4 py-2 font-mono',
					TONE[banner.tone].bar
				)}
			>
				<span class={cn('shrink-0 tracking-[0.16em] uppercase', TONE[banner.tone].text)}
					>{banner.tag}</span
				>
				<span class="text-muted-foreground">{banner.say}</span>
			</div>
		{/if}

		<!--
			The stage, laid out to the storyboard. Far left: the globe — your machine
			at the end of the wire, where the question leaves and the opened answer
			parks. Center: the certifier, a tall body the cable runs straight
			through, racking the films it stamps. Right: the GPU cluster, where the
			model commitment is revealed and the films slide in to combine — the
			proof runs in there.
		-->
		<section class="relative min-h-0 flex-1 overflow-hidden border border-border bg-card">
			<div
				class="pointer-events-none absolute inset-0 opacity-50"
				style="background-image:linear-gradient(to right,var(--grid) 1px,transparent 1px),linear-gradient(to bottom,var(--grid) 1px,transparent 1px);background-size:44px 44px"
			></div>

			<!-- the cable, in two plain runs: globe's side → certifier's left wall,
			     and certifier's right wall → the cluster. No bend — the globe is big
			     enough that the wire simply leaves its side — and no neon: the
			     payload card itself is the traffic. -->
			<div class="absolute top-[41%] right-[70%] left-[9%] h-px bg-border"></div>
			<div class="absolute top-[41%] right-[33%] left-[48%] h-px bg-border"></div>

			<!-- your machine: a globe sitting ON the wire, big enough that the cable
			     simply leaves its side — no bend, no drop -->
			<div
				class={cn(
					'absolute top-[41%] left-[6%] -translate-x-1/2 -translate-y-1/2 transition-colors duration-300',
					hotHome ? 'text-signal' : 'text-muted-foreground'
				)}
			>
				<svg
					viewBox="0 0 24 24"
					class="w-[clamp(3.6rem,6vw,6.4rem)] transition-all duration-300"
					fill="none"
					stroke="currentColor"
					stroke-width="1.3"
					aria-hidden="true"
				>
					<circle cx="12" cy="12" r="9" />
					<ellipse cx="12" cy="12" rx="4.2" ry="9" />
					<path d="M3 12h18" />
					<path d="M4.4 7.2h15.2M4.4 16.8h15.2" />
				</svg>
			</div>

			<!-- the certifier: a tall body the cable runs straight through; the films
			     it stamps rack up inside it until the proof calls for them -->
			<div
				class={cn(
					'absolute top-[8%] h-[78%] w-[clamp(280px,34vw,560px)] -translate-x-1/2 border bg-background transition-all duration-300',
					hotFpga ? 'border-signal' : 'border-border'
				)}
				style="left:{STOP[1].x}%"
			>
				<div class="flex flex-col items-center border-b border-border px-3 py-1.5">
					<span class="t-body font-mono font-semibold tracking-[0.05em]">NETWORK CERTIFIER</span>
				</div>
			</div>

			<!-- the GPU cluster: where the model runs, and where the proof combines.
			     Top-aligned with the certifier and shorter, the way the storyboard
			     draws them — the certifier is the dominant body on the wire, and
			     the films rise into this box from below. -->
			<div
				class={cn(
					'absolute top-[8%] right-[3%] left-[66%] h-[66%] flex flex-col overflow-hidden border bg-background transition-all duration-500',
					verdict
						? verdict.verdict === 'PASS'
							? 'border-verified'
							: 'border-fault'
						: hotSpark
							? 'border-signal'
							: 'border-border'
				)}
			>
				{#if working}
					<div class="ilk-sweep pointer-events-none absolute inset-x-0 h-1/4 bg-signal/10"></div>
				{/if}
				<div class="flex shrink-0 flex-col items-center gap-0.5 border-b border-border px-3 py-1.5">
					<span class="t-body font-mono font-semibold tracking-[0.05em]">GPU CLUSTER</span>
					{#if clusterStatus}
						<span
							class={cn(
								't-tag font-mono uppercase',
								verdict
									? verdict.verdict === 'PASS'
										? 'text-verified'
										: 'text-fault'
									: 'text-muted-foreground'
							)}>{clusterStatus}</span
						>
					{/if}
				</div>
				<!-- the combine: the three films stacked at true registration, in place
				     and at film size — landing IS combining, there is no handoff to a
				     larger instrument. C is the model commitment, revealed when the
				     proof begins; A and B appear the moment they land. While the prover
				     runs the two sliders rake against the backing; the verdict snaps
				     them home, and the stack IS the verdict: three shares that tile
				     leave the word black, a rogue output leaves noise. -->
				<div class="relative flex min-h-0 flex-1 flex-col items-center justify-center gap-1.5">
					<span
						class={cn(
							'font-mono text-[clamp(0.72rem,0.85vw,1.05rem)] whitespace-nowrap uppercase transition-opacity duration-400',
							regModel ? 'opacity-100' : 'opacity-0'
						)}
						style="color:{HUEC}"
						>declared model fingerprint · {regModel ? '0x' + short(regModel, 8) : '—'}</span
					>
					<div
						class="relative w-full"
						style="max-width:min({FILMW},92%);aspect-ratio:{DEFAULT_GRID.cols}/{filmStrips.pile}"
					>
						{#each [2, 0, 1] as i (i)}
							{@const on = i === 2 ? !!regModel : i === 0 ? !!regReq : !!regRsp}
							{@const ink = i === 2 ? HUEC : i === 0 ? HUEA : failB ? 'var(--fault)' : HUEB}
							{@const home = i === 1 ? filmStrips.slack : 0}
							<!-- Every sheet is drawn in the SAME pile-sized coordinate space,
							     its cells already at their home rows: registration is exact by
							     construction, instead of asking three separately-scaled boxes
							     to agree to the pixel. Cells are exactly 1x1 with crisp edges,
							     because a 5% overdraw that hides hairlines inside one sheet
							     reads as a shadow the moment sheets stack. -->
							<svg
								viewBox="0 0 {DEFAULT_GRID.cols} {filmStrips.pile}"
								preserveAspectRatio="none"
								shape-rendering="crispEdges"
								class={cn(
									'absolute inset-0 h-full w-full transition-opacity duration-400',
									on ? 'opacity-100' : 'opacity-0',
									proving && i === 0 && 'ilk-hunt-a',
									proving && i === 1 && 'ilk-hunt-b'
								)}
								aria-hidden="true"
							>
								{#each { length: filmStrips.heights[i] } as _r, r (r)}
									{#each { length: DEFAULT_GRID.cols } as _c, c (c)}
										{#if filmStrips.cells[i][r * DEFAULT_GRID.cols + c] > 0}
											<rect x={c} y={home + r} width="1" height="1" fill={ink} />
										{/if}
									{/each}
								{/each}
							</svg>
						{/each}
					</div>
				</div>
			</div>

			<!-- the payload: the text itself rides the cable, sealed or open. Fixed
			     width, wrapping to as many lines as it needs — sealing swaps every
			     character but never reshapes the envelope. -->
			<div
				class={cn(
					'absolute z-10 flex w-[clamp(170px,17vw,300px)] -translate-x-1/2 -translate-y-1/2 items-start gap-2 border px-3 py-1.5 font-mono transition-all duration-[900ms] ease-in-out motion-reduce:transition-none',
					pktSealed
						? 'border-[#d9a13b] bg-muted text-muted-foreground'
						: 'border-border bg-muted text-foreground',
					pktShown ? 'opacity-100' : 'opacity-0'
				)}
				style="left:{pktX.x}%;top:{pktX.y}%"
			>
				{#if pktSealed}
					<!-- the padlock EXISTS only while the payload is sealed: encryption
					     snaps it on, decryption takes it away. There is no open-lock
					     glyph -- absence is the open state. -->
					<svg
						viewBox="0 0 24 24"
						class="mt-[0.15em] size-[1.15em] shrink-0 text-[#d9a13b]"
						fill="none"
						stroke="currentColor"
						stroke-width="2.4"
						aria-hidden="true"
						transition:scale={{ duration: 260 }}
					>
						<rect x="4" y="11" width="16" height="10" rx="1.5" />
						<path d="M8 11V7a4 4 0 0 1 8 0v4" />
					</svg>
				{/if}
				<!-- ciphertext has no spaces to break on, so it breaks anywhere;
				     plaintext keeps its words whole -->
				<span
					class={cn(
						'min-w-0 flex-1 text-[clamp(0.95rem,1.15vw,1.4rem)] leading-snug',
						pktSealed ? 'break-all' : 'break-words'
					)}
					>{pktText}</span
				>
			</div>

			<!-- the certifier's two stamps in flight: the strip patterns themselves -->
			{@render filmchip(0, 'INPUT FINGERPRINT', reqFp, HUEA, chipA, CHIP_A, false)}
			{@render filmchip(1, 'OUTPUT FINGERPRINT', rspFp, HUEB, chipB, CHIP_B, failB)}
		</section>
	</main>

	{#if goingDown}
		<!-- CRT power-off: the lit field collapses to a scanline, the scanline to
		     a point, and a faint power glyph breathes until the machine serving
		     this page actually dies and takes the screen with it. -->
		<div class="fixed inset-0 z-50 overflow-hidden bg-black">
			<div class="ilk-crt"></div>
			<svg
				class="ilk-powerglyph"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="1.6"
				stroke-linecap="round"
				aria-label="powering off"
			>
				<path d="M12 3v8" />
				<path d="M7.2 6.4a7.5 7.5 0 1 0 9.6 0" />
			</svg>
		</div>
	{/if}
</div>
