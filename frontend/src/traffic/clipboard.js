// 导出 CSV 的交付方式：先剪贴板，再下载。
//
// 为什么不是直接 `<a download>`：答辩现场点一下"导出 CSV"，Chrome 会在页面底部
// 挂一条下载条，横在备案号与表格最后一行上面，投影时看起来像页面坏了；而这段
// 数据在答辩里只需要"能带走"。所以默认写剪贴板（可直接粘进 Excel / WPS），
// 复制被拒（无权限、非安全上下文、老浏览器）时才退回下载 —— 能力一点不丢。
//
// 带 BOM 是给 Excel 认 UTF-8 用的：不带的话中文列名会变乱码，而"导出后打开是
// 乱码"和"导出失败"在使用者眼里是同一件事。

const BOM = '\ufeff'

function download(text, filename, type) {
  const blob = new Blob([text], { type })
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  document.body.appendChild(link)
  link.click()
  link.remove()
  // 立刻 revoke 会让部分浏览器拿不到数据，推迟一拍。
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/**
 * 把一段 CSV 交给使用者。
 * @returns {Promise<{mode:'clipboard'|'download', rows:number, error?:string}>}
 */
export async function deliverCsv(text, filename) {
  const payload = BOM + String(text ?? '')
  const rows = Math.max(0, String(text ?? '').trim().split(/\r?\n/).length - 1)
  try {
    if (!navigator.clipboard || !navigator.clipboard.writeText) throw new Error('NO_CLIPBOARD')
    await navigator.clipboard.writeText(payload)
    return { mode: 'clipboard', rows }
  } catch (error) {
    download(payload, filename, 'text/csv;charset=utf-8')
    return { mode: 'download', rows, error: error?.message || String(error) }
  }
}

export function csvDeliveryText(result) {
  if (!result) return ''
  if (result.mode === 'clipboard') {
    return `已复制 ${result.rows} 行 CSV 到剪贴板，可直接粘贴到表格（未触发下载）`
  }
  return `浏览器未允许剪贴板，已改为下载文件（${result.rows} 行）`
}
