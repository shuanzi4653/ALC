const DEMO_CASE = 'fog-20250105'

export function bootstrapCaseMode() {
  let params
  try {
    params = new URLSearchParams(window.location.search)
  } catch (_) {
    return
  }
  if ((params.get('case') || '').trim()) return
  const demo = params.get('mode') === 'demo'
  if (!demo) return
  params.set('case', DEMO_CASE)
  try {
    window.location.replace(`${window.location.pathname}?${params.toString()}${window.location.hash}`)
  } catch (_) {
  }
}
