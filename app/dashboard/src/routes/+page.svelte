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
	 * each passing packet; the fingerprints slide into the GPU cluster and combine
	 * there, because that is where the proof actually runs. The numbers an engineer
	 * wants are on the console and in /lab.
	 */
	import FingerprintRegister, { type Stage } from '$lib/components/fingerprint-register.svelte';
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
	const STOP = [14, 41, 63];
	let pktX = $state(STOP[0]);
	let pktText = $state('');
	let pktSealed = $state(false);
	let pktShown = $state(false);

	let reqFp = $state<string | null>(null);
	let rspFp = $state<string | null>(null);
	let modelFp = $state<string | null>(null);
	/**
	 * The two fingerprints the certifier mints, as flying FILMS: the strip's own
	 * cell pattern is stamped out of the certifier as the packet passes, slides
	 * across into the GPU cluster — because the proof that combines them runs on
	 * the Spark, not in the cable — and is absorbed into the register there.
	 * 'out' is the stamp emerging; 'docked' is arrived over the register; 'gone'
	 * is absorbed into it (the register is then showing the same strip).
	 */
	type Chip = 'hidden' | 'out' | 'docked' | 'gone';
	let chipA = $state<Chip>('hidden');
	let chipB = $state<Chip>('hidden');
	/** the proof is in flight: the register hunts for the seat until this clears */
	let proving = $state(false);
	let promptText = $state('');
	let answer = $state('');
	let verdict = $state<Verdict | null>(null);
	let elapsed = $state('');

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

	/** a long answer still has to fit the chip; the full text lands in the corner */
	const clip = (s: string, n = 44) => (s.length > n ? s.slice(0, n - 1) + '…' : s);

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
		proving = false;
		promptText = '';
		answer = '';
		verdict = null;
		elapsed = '';
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

	/** the film coming out of the certifier, sliding across, and being absorbed */
	async function emitChip(which: 'A' | 'B', gen: number) {
		const set = (v: Chip) => (which === 'A' ? (chipA = v) : (chipB = v));
		set('out');
		if (!(await step(frozen() ? 30 : 420, gen))) return;
		set('docked');
		if (!(await step(frozen() ? 30 : 1300, gen))) return;
		set('gone');
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
		caption = 'The certifier stamps a fingerprint off the sealed bytes as they pass.';
		log(`CERT   inbound  ${short(reqFp, 16)} audit=${d.request_audit ? 'PASS' : 'FAIL'}`);
		// the stamp and the onward hop overlap on purpose: the certifier never
		// holds traffic, it reads it on the way past
		await emitChip('A', gen);
		if (!(await step(700, gen))) return;

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
		scrambleTo(cipherOf(d.ct_out, Math.min(clip(text).length, 44)));
		caption = '…and encrypts it for the trip back.';
		if (!(await step(1100, gen))) return;

		phase = 'rsp';
		pktX = STOP[1];
		hotSpark = false;
		hotFpga = true;
		if (!(await step(950, gen))) return;

		rspFp = d.response_digest ?? null;
		caption = 'The answer is fingerprinted on the way out.';
		log(`CERT   outbound ${short(rspFp, 16)} audit=${d.response_audit ? 'PASS' : 'FAIL'}`);
		await emitChip('B', gen);
		if (!(await step(700, gen))) return;

		pktX = STOP[0];
		hotFpga = false;
		if (!(await step(950, gen))) return;
		pktSealed = false;
		scrambleTo(clip(text));
		caption = 'Only your machine holds the key that opens it.';
		if (!(await step(1000, gen))) return;
		pktShown = false;
		answer = text;
		log(`OPEN   ${text}`);
	}

	async function runProve(gen: number) {
		phase = 'prove';
		hotSpark = true;
		// `proving` is what puts the register into its search, and it stays up until
		// the verdict lands however long that takes -- the animation is paced by the
		// prover, not by a timer that guesses at it.
		proving = true;
		caption =
			'Both fingerprints are now in the cluster. It has to prove they came from the promised model.';
		if (!(await step(1100, gen))) return;
	}

	async function runVerdict(d: any, gen: number) {
		// A verdict for a run that has already been superseded -- Reset pressed, or a
		// second Prompt -- must not repaint the panel it is no longer about.
		if (gen !== generation) return;
		verdict = d.result as Verdict;
		elapsed = d.secs ? `${d.secs}s` : '';
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
		socket.on('beat:error', (d: any) => {
			caption = 'Something went wrong. Press RESET and try again.';
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

	// ── the register ───────────────────────────────────────────────────────────
	// Three sheets: the two the certifier stamped on the way past, and the model's
	// own, which is fixed before anything is sent. They combine inside the GPU
	// cluster because that is where the proof runs; the register hunts while the
	// prover does and settles when it rules.
	const fpStage = $derived(
		(verdict
			? verdict.verdict === 'PASS'
				? 'pass'
				: 'fail'
			: proving
				? 'searching'
				: reqFp
					? 'dealing'
					: 'idle') as Stage
	);

	// ── the strip that is never dismissible when it matters ────────────────────
	/**
	 * What an audience has a right to know before they believe the screen. The
	 * simulator outranks the tamper because "none of this happened" is the more
	 * important of the two. A live, honest run has nothing to disclaim, so the
	 * strip only exists when one of the warnings holds; the server's own mode
	 * label rides as the stage tooltip for whoever is running the demo.
	 */
	const banner = $derived(
		simRun || simMode
			? {
					tag: 'Simulated',
					tone: 'caution' as const,
					say: `no hardware connected — everything on this screen is made up by the browser${armed ? ', with the tamper switch on' : ''}`
				}
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
	/** and your own machine lights up for the two moments the key is in use */
	const hotHome = $derived(pktShown && pktX === STOP[0]);
	const TONE = {
		caution: { bar: 'border-l-caution', text: 'text-caution' },
		fault: { bar: 'border-l-fault', text: 'text-fault' }
	};

	// ── the flying films: geometry and dressing ────────────────────────────────
	// Stage coordinates for a film's journey: minted just under the certifier,
	// then a long slide right into the cluster, where the register absorbs it.
	// C never travels — the model commitment was in the cluster before anything
	// ran, so it only ever appears in the tray.
	const CHIP = {
		A: { out: { x: 41, y: 54 }, dock: { x: 83, y: 40 } },
		B: { out: { x: 41, y: 54 }, dock: { x: 83, y: 40 } }
	};
	const HUEA = '#b6e04c';
	const HUEB = '#3fd2ea';
	const HUEC = '#c98cf6';
	const failB = $derived(!!verdict && verdict.verdict !== 'PASS');
	// The films' own cell patterns — the same strips the register is composing,
	// derived from the same digests, so what flies is what lands.
	const filmMask = stencil(DEFAULT_WORD, DEFAULT_FACE, DEFAULT_GRID);
	const filmShares = $derived(build(reqFp ?? '', rspFp ?? '', modelFp ?? '', !failB, filmMask));
	const filmStrips = $derived(strips(filmShares, DEFAULT_GRID, 2, modelFp ?? '', 0.5));
	const clusterStatus = $derived(
		verdict
			? verdict.verdict === 'PASS'
				? `verified${elapsed ? ' · ' + elapsed : ''}`
				: 'rejected'
			: proving
				? 'aligning the fingerprints…'
				: phase === 'gen'
					? 'running the model'
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

{#snippet station(left: number, name: string, sub: string, hot: boolean, big = false)}
	<div
		class={cn(
			'absolute flex -translate-x-1/2 flex-col items-center justify-center gap-1 overflow-hidden border bg-background transition-all duration-300',
			big
				? 'top-[8%] h-[38%] w-[clamp(170px,21vw,340px)]'
				: 'top-[12%] h-[28%] w-[clamp(120px,13vw,220px)]',
			hot ? 'border-signal shadow-[0_0_30px_-4px_var(--signal)]' : 'border-border'
		)}
		style="left:{left}%"
	>
		<div class="t-body font-mono font-semibold tracking-[0.05em]">{name}</div>
		<div class="t-tag px-2 text-center font-mono leading-tight text-muted-foreground uppercase">
			{sub}
		</div>
	</div>
{/snippet}

{#snippet filmchip(
	idx: number,
	role: string,
	hex: string | null,
	hue: string,
	state: Chip,
	pos: { out: { x: number; y: number }; dock: { x: number; y: number } },
	bad: boolean
)}
	{@const at = state === 'out' ? pos.out : pos.dock}
	{@const ink = bad ? 'var(--fault)' : hue}
	{@const rows = filmStrips.heights[idx]}
	<div
		class={cn(
			'absolute z-20 flex w-[clamp(110px,12vw,200px)] -translate-x-1/2 -translate-y-1/2 flex-col items-center gap-0.5 transition-all duration-[1100ms] ease-in-out motion-reduce:transition-none',
			state === 'hidden' && 'scale-75 opacity-0',
			state === 'out' && 'opacity-100 duration-[420ms]',
			state === 'docked' && 'opacity-100',
			state === 'gone' && 'scale-110 opacity-0 duration-[500ms]'
		)}
		style="left:{at.x}%;top:{at.y}%"
	>
		<span class="t-tag font-mono whitespace-nowrap" style="color:{ink}"
			>{role} · {hex ? '0x' + short(hex, 8) : '—'}</span
		>
		<!-- the strip's actual cells: what flies is what the register composes -->
		<svg
			viewBox="0 0 {DEFAULT_GRID.cols} {rows}"
			class="w-full"
			preserveAspectRatio="none"
			style="filter:drop-shadow(0 0 6px {ink})"
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
			The stage. Left two thirds: your machine and the certifier on the wire, the
			payload text travelling between them. Right third: the GPU cluster, a tall
			box holding the model's own fingerprint and the register the other two
			slide into — the proof runs in there, so that is where they combine.
		-->
		<section class="relative min-h-0 flex-1 overflow-hidden border border-border bg-card">
			<div
				class="pointer-events-none absolute inset-0 opacity-50"
				style="background-image:linear-gradient(to right,var(--grid) 1px,transparent 1px),linear-gradient(to bottom,var(--grid) 1px,transparent 1px);background-size:44px 44px"
			></div>

			<!-- a drop from each machine down to the cable it is spliced into -->
			<div class="absolute top-[40%] h-[18%] w-px bg-border" style="left:{STOP[0]}%"></div>
			<div class="absolute top-[46%] h-[12%] w-px bg-border" style="left:{STOP[1]}%"></div>

			<!-- the cable, running from your machine into the cluster's mouth -->
			<div class="absolute top-[58%] right-[32%] left-[5%] h-px bg-border"></div>
			<div
				class={cn(
					'absolute top-[58%] right-[32%] left-[5%] h-[2px] transition-opacity duration-500',
					pktShown ? 'ilk-flow opacity-80' : 'opacity-0'
				)}
			></div>

			{@render station(STOP[0], 'YOUR MACHINE', 'holds the key', hotHome)}
			{@render station(STOP[1], 'NETWORK CERTIFIER', 'fingerprints every packet', hotFpga, true)}

			<!-- the GPU cluster: where the model runs, and where the proof combines -->
			<div
				class={cn(
					'absolute inset-y-[5%] right-[2%] left-[68%] flex flex-col overflow-hidden border bg-background transition-all duration-500',
					verdict
						? verdict.verdict === 'PASS'
							? 'border-verified shadow-[0_0_40px_-4px_var(--verified)]'
							: 'border-fault shadow-[0_0_40px_-4px_var(--fault)]'
						: hotSpark
							? 'border-signal shadow-[0_0_30px_-4px_var(--signal)]'
							: 'border-border'
				)}
			>
				{#if working}
					<div class="ilk-sweep pointer-events-none absolute inset-x-0 h-1/4 bg-signal/10"></div>
				{/if}
				<div
					class="flex shrink-0 items-baseline justify-between gap-2 border-b border-border px-3 py-1.5"
				>
					<span class="t-body font-mono font-semibold tracking-[0.05em]">GPU CLUSTER</span>
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
				</div>
				<!-- the register: three fingerprints hunting for the seat, then the word -->
				<FingerprintRegister req={reqFp} rsp={rspFp} model={modelFp} stage={fpStage} embed />
				<!-- the tray: which fingerprints the cluster is holding -->
				<div
					class="flex h-[clamp(2rem,5vh,3rem)] shrink-0 items-center justify-between border-t border-border px-3"
				>
					{#each [
						['REQUEST', reqFp, HUEA],
						['RESPONSE', rspFp, failB ? 'var(--fault)' : HUEB],
						['MODEL · llama-1.1b', modelFp, HUEC]
					] as [role, hex, hue] (role)}
						<div
							class={cn(
								'flex flex-col transition-opacity duration-500',
								hex ? 'opacity-100' : 'opacity-25'
							)}
						>
							<span class="t-tag font-mono" style="color:{hue}">{role}</span>
							<span
								class="tabular font-mono text-[clamp(0.6rem,0.7vw,0.85rem)] leading-tight font-semibold"
								style="color:{hue}">{hex ? '0x' + short(hex, 8) : '—'}</span
							>
						</div>
					{/each}
				</div>
			</div>

			<!-- the payload: the text itself rides the cable, sealed or open -->
			<div
				class={cn(
					'absolute top-[58%] z-10 flex max-w-[38%] -translate-x-1/2 -translate-y-1/2 items-center gap-2 overflow-hidden border px-3 py-1.5 font-mono whitespace-nowrap transition-all duration-[900ms] ease-in-out motion-reduce:transition-none',
					pktSealed
						? 'border-border bg-muted text-muted-foreground'
						: 'border-signal bg-signal/15 text-signal shadow-[0_0_22px_-3px_var(--signal)]',
					pktShown ? 'opacity-100' : 'opacity-0'
				)}
				style="left:{pktX}%"
			>
				<svg
					viewBox="0 0 24 24"
					class="size-[1.15em] shrink-0"
					fill="none"
					stroke="currentColor"
					stroke-width="2.4"
					aria-hidden="true"
				>
					<rect x="4" y="11" width="16" height="10" rx="1.5" />
					{#if pktSealed}
						<path d="M8 11V7a4 4 0 0 1 8 0v4" />
					{:else}
						<path d="M8 11V7a4 4 0 0 1 7.4-2" />
					{/if}
				</svg>
				<span class="t-body overflow-hidden">{pktText}</span>
			</div>

			<!-- the certifier's two stamps in flight: the strip patterns themselves -->
			{@render filmchip(0, 'REQUEST', reqFp, HUEA, chipA, CHIP.A, false)}
			{@render filmchip(1, 'RESPONSE', rspFp, HUEB, chipB, CHIP.B, failB)}
		</section>
	</main>

	{#if goingDown}
		<div
			class="fixed inset-0 z-50 flex flex-col items-center justify-center gap-4 bg-background/95 backdrop-blur-sm"
		>
			<span class="t-big font-mono tracking-[0.14em] text-fault uppercase">Powering off</span>
			<p class="t-lead max-w-[34ch] text-center text-muted-foreground">
				Both machines are halting. This screen is served by one of them, so it will go dark.
			</p>
		</div>
	{/if}
</div>
