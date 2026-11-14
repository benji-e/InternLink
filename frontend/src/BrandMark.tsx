export function BrandMark({ suffix }: { suffix?: string }) {
  return (
    <div className="brand-lockup">
      <span className="brand-name">intern<span>link</span></span>
      {suffix && <span className="brand-region">{suffix}</span>}
    </div>
  )
}
