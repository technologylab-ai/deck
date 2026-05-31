import streamDeck, { LogLevel } from "@elgato/streamdeck";

import { OpenTarget } from "./actions/open-target";

// `deck` does the real work and logs to its own file; keep the plugin log quiet
// unless we're chasing a problem.
streamDeck.logger.setLevel(LogLevel.INFO);

streamDeck.actions.registerAction(new OpenTarget());

streamDeck.connect();
