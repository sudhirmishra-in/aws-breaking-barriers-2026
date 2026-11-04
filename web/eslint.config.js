import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";
import vue from "eslint-plugin-vue";

export default tseslint.config(
  { ignores: ["dist", "node_modules"] },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...vue.configs["flat/recommended"],
  {
    files: ["**/*.vue"],
    languageOptions: { parserOptions: { parser: tseslint.parser } },
  },
  { files: ["public/pcm-worklet.js"], languageOptions: { globals: { AudioWorkletProcessor: "readonly", registerProcessor: "readonly" } } },
  { files: ["src/views/**/*.vue"], rules: { "vue/multi-word-component-names": "off" } }, // route views, not reusable components
  {
    languageOptions: { globals: { ...globals.browser } },
    rules: {
      // Formatting is not enforced here; correctness rules are.
      "vue/max-attributes-per-line": "off", "vue/singleline-html-element-content-newline": "off", "vue/html-self-closing": "off",
      "vue/multiline-html-element-content-newline": "off", "vue/html-indent": "off", "vue/html-closing-bracket-newline": "off",
      "vue/first-attribute-linebreak": "off", "vue/attributes-order": "off",
      "vue/no-v-html": "off", // renderMarkdown() escapes all HTML before adding tags (covered by a unit test)
    },
  },
);
