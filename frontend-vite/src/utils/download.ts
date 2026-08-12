const isCap = !!import.meta.env.VITE_CAPACITOR

export async function downloadFileByUrl(url: string, filename: string) {
  if (isCap) {
    const { Filesystem, Directory } = await import('@capacitor/filesystem')
    const { Share } = await import('@capacitor/share')
    const { default: axiosLib } = await import('axios')
    const fullUrl = url.startsWith('http') ? url : `${import.meta.env.VITE_STATIC_ORIGIN || ''}${url}`
    const res = await axiosLib.get(fullUrl, { responseType: 'arraybuffer' })
    const blob = new Blob([res.data as ArrayBuffer])
    const base64 = await new Promise<string>((resolve) => {
      const reader = new FileReader()
      reader.onload = () => {
        const dataUrl = reader.result as string
        resolve(dataUrl.split(',')[1] ?? '')
      }
      reader.readAsDataURL(blob)
    })
    const result = await Filesystem.writeFile({
      path: filename,
      data: base64,
      directory: Directory.Cache,
    })
    await Share.share({ url: result.uri, title: filename })
  } else {
    window.open(url, '_blank')
  }
}
