import { useEffect, useState, type MouseEvent } from 'react'

/** A tiny history-based router: the site only needs a handful of paths. */

const listeners = new Set<() => void>()

export function navigate(to: string, { replace = false } = {}) {
  if (to === window.location.pathname + window.location.search) return
  if (replace) window.history.replaceState({}, '', to)
  else window.history.pushState({}, '', to)
  window.scrollTo(0, 0)
  listeners.forEach((listener) => listener())
}

export function useLocation() {
  const read = () => ({ path: window.location.pathname.replace(/\/+$/, '') || '/', search: window.location.search })
  const [location, setLocation] = useState(read)
  useEffect(() => {
    const update = () => setLocation(read())
    listeners.add(update)
    window.addEventListener('popstate', update)
    return () => {
      listeners.delete(update)
      window.removeEventListener('popstate', update)
    }
  }, [])
  return location
}

/** Use on <a href> so links still work with middle-click and "open in new tab". */
export function linkTo(to: string) {
  return {
    href: to,
    onClick: (event: MouseEvent<HTMLAnchorElement>) => {
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return
      event.preventDefault()
      navigate(to)
    },
  }
}
