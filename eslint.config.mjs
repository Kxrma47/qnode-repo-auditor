import js from "@eslint/js";
import globals from "globals";

export default [
  {
    files: ["qnode_auditor/static/app.js"],
    languageOptions: { globals: globals.browser, sourceType: "script" },
    rules: js.configs.recommended.rules,
  },
];
