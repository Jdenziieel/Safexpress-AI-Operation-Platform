import { defineConfig } from 'vitest/config';
import { agent } from '@agent';

export default defineConfig({
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: './src/setupTests.js',
    include: ['src/**/*.test.jsx'],
    reporters: 'verbose',
    transform: {
      '^.+\\.jsx?$': 'babel-jest',
    },
    plugins: [agent()],
  },
});