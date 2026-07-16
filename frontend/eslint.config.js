import js from '@eslint/js'
import { defineConfig, globalIgnores } from 'eslint/config'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'
import tseslint from 'typescript-eslint'

const browserFiles = ['src/**/*.{ts,vue}', 'stats/**/*.js', 'smoke-test.mjs']
const nodeFiles = [
  '*.{js,mjs,cjs,ts}',
  'electron/**/*.{js,mjs,cjs}',
  'scripts/**/*.{js,mjs,cjs}',
  'tests/**/*.{js,mjs,cjs,ts}',
]

export default defineConfig(
  globalIgnores(['coverage/**', 'dist/**', 'node_modules/**', 'public/live2d/**']),
  {
    linterOptions: {
      reportUnusedDisableDirectives: 'error',
      reportUnusedInlineConfigs: 'error',
    },
  },
  {
    files: ['**/*.{js,mjs,cjs}'],
    extends: [js.configs.recommended],
  },
  {
    files: ['**/*.ts'],
    extends: [tseslint.configs.recommended],
  },
  {
    files: ['**/*.vue'],
    extends: [tseslint.configs.recommended, pluginVue.configs['flat/essential']],
  },
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
      },
    },
  },
  {
    files: browserFiles,
    languageOptions: {
      globals: {
        ...globals.browser,
        Chart: 'readonly',
      },
    },
  },
  {
    files: ['worker/**/*.{js,mjs,cjs}'],
    languageOptions: {
      globals: globals.serviceworker,
    },
  },
  {
    files: nodeFiles,
    languageOptions: {
      globals: globals.node,
    },
  },
  {
    files: ['electron/**/*.cjs'],
    languageOptions: {
      globals: globals.commonjs,
      sourceType: 'commonjs',
    },
  },
  {
    files: ['**/*.{ts,vue}'],
    rules: {
      'no-undef': 'off',
    },
  },
)
