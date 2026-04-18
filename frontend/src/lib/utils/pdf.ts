import { SourceListResponse } from '@/lib/types/api'

/**
 * Check if a source is a PDF file
 */
export function isPdfSource(source: SourceListResponse): boolean {
  if (!source.asset?.file_path) return false
  const lowerPath = source.asset.file_path.toLowerCase()
  return lowerPath.endsWith('.pdf')
}

/**
 * Get the PDF download URL for a source
 */
export function getPdfUrl(sourceId: string): string {
  return `/api/sources/${encodeURIComponent(sourceId)}/download`
}

function escapePdfText(input: string): string {
  return input.replace(/\\/g, '\\\\').replace(/\(/g, '\\(').replace(/\)/g, '\\)')
}

export function createMockPdfBytes(title: string): Uint8Array {
  const contentText = escapePdfText(`Open Notebook Mock PDF: ${title}`)
  const contentStream = `BT\n/F1 18 Tf\n72 760 Td\n(${contentText}) Tj\nET\n`

  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>',
    `<< /Length ${contentStream.length} >>\nstream\n${contentStream}endstream`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]

  let pdf = '%PDF-1.4\n'
  const offsets: number[] = [0]

  objects.forEach((object, index) => {
    const objectNumber = index + 1
    offsets[objectNumber] = pdf.length
    pdf += `${objectNumber} 0 obj\n${object}\nendobj\n`
  })

  const startXref = pdf.length
  pdf += `xref\n0 ${objects.length + 1}\n`
  pdf += '0000000000 65535 f \n'

  for (let i = 1; i <= objects.length; i += 1) {
    pdf += `${offsets[i].toString().padStart(10, '0')} 00000 n \n`
  }

  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${startXref}\n%%EOF`

  return new TextEncoder().encode(pdf)
}