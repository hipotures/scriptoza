'use strict';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import St from 'gi://St';

export async function reload() {
    const extension = Main.extensionManager.lookup('codex-status@scriptoza');
    if (extension?.state !== 1 || !extension.stateObj)
        throw new Error('Codex Status must be enabled before reloading');
    const module = await import(`${extension.dir.get_child('extension.js').get_uri()}?revision=${Date.now()}`);
    const replacement = new module.default({...extension.metadata, dir: extension.dir, path: extension.path});
    const previous = extension.stateObj;
    previous.disable();
    try {
        const theme = St.ThemeContext.get_for_stage(global.stage).get_theme();
        const stylesheet = extension.dir.get_child('stylesheet.css');
        theme.unload_stylesheet(stylesheet);
        theme.load_stylesheet(stylesheet);
        replacement.enable();
        extension.stateObj = replacement;
    } catch (error) {
        replacement.disable();
        previous.enable();
        throw error;
    }
}
