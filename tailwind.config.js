/** @type {import('tailwindcss').Config} */
// Color values MUST mirror static/css/tokens.css (the source of truth).
// The 2026-07-05 Deep Water overhaul unified these; do not let them drift.
module.exports = {
  content: ['./templates/**/*.html'],
  theme: {
    extend: {
      colors: {
        base: '#090E14',
        tile: '#111A24',
        card: '#141E2A',
        inset: '#0E1620',
        elevated: '#1A2633',
        hover: '#22303F',
        accent: {
          DEFAULT: '#46B3C4',
          hover: '#5FC2D2',
        },
        gold: {
          DEFAULT: '#E0A446',
          hover: '#EAB25E',
        },
        blue: {
          DEFAULT: '#1B7FAF',
          bright: '#3DB4E0',
        },
        supply: '#55B678',
        deficit: '#D1742E',
        'text-primary': '#E7EEF2',
        'text-secondary': '#8FA3AE',
        'text-tertiary': '#7E93A4',
      },
      fontFamily: {
        display: ["'Public Sans'", 'sans-serif'],
        mono: ["'Public Sans'", 'sans-serif'],
      },
      borderRadius: {
        sm: '6px',
        md: '10px',
        lg: '14px',
        xl: '16px',
      },
      spacing: {
        xs: '4px',
        sm: '8px',
        md: '16px',
        lg: '24px',
        xl: '32px',
        '2xl': '48px',
        '3xl': '64px',
      },
    },
  },
  plugins: [],
}
