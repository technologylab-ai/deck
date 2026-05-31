import streamDeck, {
	action,
	type Action,
	type DidReceiveSettingsEvent,
	type JsonValue,
	type KeyAction,
	type KeyDownEvent,
	type KeyUpEvent,
	type SendToPluginEvent,
	SingletonAction,
	type WillAppearEvent,
} from "@elgato/streamdeck";
import { execFileSync, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

/**
 * Absolute path to the `deck` shim. Stream Deck launches plugins with a minimal
 * PATH (no Homebrew), so we cannot rely on `deck` being resolvable — the shim
 * that `uv tool install` drops at ~/.local/bin/deck is the contract.
 */
const DECK = join(homedir(), ".local", "bin", "deck");

/** Hold a key longer than this (ms) to close the target instead of opening it. */
const LONG_PRESS_MS = 500;

/** Per-button settings persisted by Stream Deck. */
type OpenSettings = {
	/** Target name from `deck list` (chosen in the Property Inspector dropdown). */
	target?: string;
	/** Button title. Seeded with the target name; clear it for a blank title. */
	title?: string;
	/** The target the title was last auto-seeded for (so we don't clobber edits). */
	titleSeededFor?: string;
};

/**
 * "Open Target" — a thin shell over the `deck` CLI. The plugin holds no logic of
 * its own: the dropdown is populated from `deck list --json`, the button image
 * comes from `deck icon <target>`, opening runs `deck open <target>`, and a
 * long-press runs `deck close <target>`.
 *
 * Tap = open/focus. Hold (>{@link LONG_PRESS_MS}ms) = close (quit the app, or
 * close the matched browser tab). The close fires the moment the threshold is
 * reached while still held, so there's no need to guess on release.
 */
@action({ UUID: "ai.technologylab.deck.open" })
export class OpenTarget extends SingletonAction<OpenSettings> {
	/** Pending long-press timers, keyed by action instance id. */
	private readonly holdTimers = new Map<string, NodeJS.Timeout>();
	/** Action ids whose long-press already fired (so keyUp doesn't also open). */
	private readonly longFired = new Set<string>();

	override onWillAppear(ev: WillAppearEvent<OpenSettings>): Promise<void> {
		return this.render(ev.action, ev.payload.settings);
	}

	override onDidReceiveSettings(ev: DidReceiveSettingsEvent<OpenSettings>): Promise<void> {
		return this.render(ev.action, ev.payload.settings);
	}

	override onKeyDown(ev: KeyDownEvent<OpenSettings>): void {
		const id = ev.action.id;
		const target = ev.payload.settings.target;
		this.longFired.delete(id);

		// Arm the long-press: if the key is still held when this fires, close.
		const timer = setTimeout(() => {
			this.holdTimers.delete(id);
			this.longFired.add(id);
			void this.runDeck(ev.action, "close", target);
		}, LONG_PRESS_MS);
		this.holdTimers.set(id, timer);
	}

	override onKeyUp(ev: KeyUpEvent<OpenSettings>): void {
		const id = ev.action.id;
		const timer = this.holdTimers.get(id);
		if (timer) {
			clearTimeout(timer);
			this.holdTimers.delete(id);
		}
		// Released after the long-press already fired → close handled, don't open.
		if (this.longFired.delete(id)) {
			return;
		}
		void this.runDeck(ev.action, "open", ev.payload.settings.target);
	}

	/**
	 * Datasource handler for the Property Inspector's `<sdpi-select>`: returns the
	 * live target list so adding a target to targets.toml needs no plugin change.
	 */
	override async onSendToPlugin(ev: SendToPluginEvent<JsonValue, OpenSettings>): Promise<void> {
		const payload = ev.payload as { event?: string };
		if (payload?.event !== "getTargets") {
			return;
		}

		let items: { label: string; value: string }[] = [];
		if (existsSync(DECK)) {
			try {
				const out = execFileSync(DECK, ["list", "--json"], { encoding: "utf-8" });
				const targets = JSON.parse(out) as { name: string }[];
				items = targets.map((t) => ({ label: t.name, value: t.name }));
			} catch (err) {
				streamDeck.logger.error("deck list --json failed", err);
			}
		} else {
			streamDeck.logger.error(`deck shim not found at ${DECK}`);
		}

		await streamDeck.ui.current?.sendToPropertyInspector({ event: "getTargets", items });
	}

	/** Run `deck <verb> <target>` and reflect success/failure on the key. */
	private async runDeck(action: KeyAction<OpenSettings>, verb: "open" | "close", target?: string): Promise<void> {
		if (!target) {
			streamDeck.logger.warn(`key ${verb} with no target selected`);
			await action.showAlert();
			return;
		}
		if (!existsSync(DECK)) {
			streamDeck.logger.error(`deck shim not found at ${DECK}`);
			await action.showAlert();
			return;
		}

		// Fire-and-forget: the press should feel instant and `deck` is idempotent.
		const child = spawn(DECK, [verb, target], { stdio: "ignore" });
		child.on("error", (err) => {
			streamDeck.logger.error(`failed to spawn deck ${verb} ${target}`, err);
			void action.showAlert();
		});
		child.on("exit", (code) => {
			if (code === 0) {
				void action.showOk();
			} else {
				streamDeck.logger.warn(`deck ${verb} ${target} exited with ${code}`);
				void action.showAlert();
			}
		});
	}

	/** Paint the button: app/favicon icon from `deck icon`, title = target name. */
	private async render(action: Action<OpenSettings>, settings: OpenSettings): Promise<void> {
		const target = settings.target;
		if (!action.isKey()) {
			return;
		}
		if (!target) {
			// No selection yet — leave the manifest's default image/title in place.
			return;
		}

		if (existsSync(DECK)) {
			try {
				const dataUrl = execFileSync(DECK, ["icon", target], { encoding: "utf-8" }).trim();
				if (dataUrl) {
					await action.setImage(dataUrl);
				}
			} catch (err) {
				streamDeck.logger.warn(`deck icon ${target} failed`, err);
			}
		}

		// Seed the title field with the target name the first time a target is
		// chosen (or when the target changes and the title wasn't customized), so
		// the name shows by default AND lives in the PI field where it can be
		// edited — or cleared for a genuinely blank title. Keyed on
		// `titleSeededFor` rather than title-presence, so clearing the field
		// (empty string OR a deleted key) is respected instead of snapping back.
		const seededFor = settings.titleSeededFor;
		if (seededFor !== target && (settings.title === undefined || settings.title === seededFor)) {
			await action.setSettings({ ...settings, title: target, titleSeededFor: target });
			await action.setTitle(target);
			return;
		}
		await action.setTitle(settings.title ?? "");
	}
}
