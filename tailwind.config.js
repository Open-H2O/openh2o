/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./templates/**/*.html'],
  theme: {
    extend: {
      colors: {
        base: '#040608',
        card: '#080b10',
        inset: '#050709',
        elevated: '#0e1219',
        hover: '#141a22',
        gold: {
          DEFAULT: '#E4A317',
          hover: '#D4952A',
        },
        blue: {
          DEFAULT: '#1B7FAF',
          bright: '#3DB4E0',
        },
        'text-primary': '#e8edf4',
        'text-secondary': '#8899aa',
        'text-tertiary': '#4d5e6f',
      },
      fontFamily: {
        display: ["'Public Sans'", 'sans-serif'],
        mono: ["'JetBrains Mono'", 'monospace'],
      },
      borderRadius: {
        sm: '6px',
        md: '10px',
        lg: '16px',
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
