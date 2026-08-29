import { defineConfig } from 'vite'
import { svelte } from '@sveltejs/vite-plugin-svelte'

// Le front est compilé dans le paquet Python : c'est ce dossier que
// `web/server.py` sert, et que PyInstaller embarque. Pas de dossier `dist`
// séparé qu'on oublierait de recopier.
export default defineConfig({
  plugins: [svelte()],
  build: {
    outDir: '../concertcutter/web/static',
    emptyOutDir: true,
    // Les noms portent une empreinte, et c'est délibéré : sans elle, une
    // version suivante de ConcertCutter servirait `assets/app.js` à un
    // navigateur qui garde l'ancien en cache et ne le redemande pas. La
    // fenêtre affiche alors l'interface d'avant, sans rien dire.
  },
  server: {
    // `npm run dev` sert la page, mais l'API reste celle du serveur Python
    // lancé à côté : sans ce renvoi, le rechargement à chaud n'aurait rien à
    // afficher.
    proxy: {
      '/api': 'http://127.0.0.1:8722',
    },
  },
})
