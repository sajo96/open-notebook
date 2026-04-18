import { pdfjs } from 'react-pdf'

// Use local worker chunk to keep worker version in lockstep with installed pdfjs-dist.
pdfjs.GlobalWorkerOptions.workerSrc = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url).toString()