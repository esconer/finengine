/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
    plugins: [react()],
    test: {
        globals: true,
        environment: 'jsdom',
        setupFiles: ['./src/test/setup.ts'],
        coverage: {
            provider: 'v8',
            reporter: ['text', 'json', 'html'],
            exclude: [
                'node_modules/',
                'src/test/',
                '**/*.d.ts',
                '**/*.config.*',
                '**/coverage/**',
                '**/dist/**'
            ],
            thresholds: {
                global: {
                    branches: 80,
                    functions: 80,
                    lines: 80,
                    statements: 80
                }
            }
        },
        includeSource: ['src/**/*.{js,ts,tsx}'],
        css: true,
        reporters: ['default', 'html'],
        outputFile: 'test-results.xml'
    },
    resolve: {
        alias: {
            '@': path.resolve(import.meta.dirname || process.cwd(), './src'),
        },
    },
    define: {
        global: 'globalThis',
    },
})