import React from 'react'

import pinkSlipArt from '../assets/pink-slip.png'
import sosCardArt from '../assets/sos-card.png'
import uniteFistArt from '../assets/unite-fist.png'

export function PinkSlip({ size = 'size-4.5' }) {
  return <img src={pinkSlipArt} alt="Pink Slip" className={`${size} shrink-0 object-contain`} />
}

export function SosCard({ size = 'size-4.5' }) {
  return <img src={sosCardArt} alt="SOS Card" className={`${size} shrink-0 object-contain`} />
}

export function UniteFist({ size = 'size-4.5' }) {
  return <img src={uniteFistArt} alt="Unite" className={`${size} shrink-0 object-contain`} />
}

export function OrganicLeaf({ size = 'size-3.5' }) {
  return (
    <span
      title="Organic Gag (Extra damage / hit chance)"
      className="rounded bg-emerald-100 text-emerald-950 border border-emerald-300 px-1 py-0.2 text-[8px] font-black uppercase tracking-wider shrink-0 inline-flex items-center gap-0.5 shadow-2xs"
    >
      🍃 ORG
    </span>
  )
}

export function GagIcon({ track, level, size = 'size-7', className = '' }) {
  if (!track || !level) return null
  const src = `assets/gag-${track}-${level}.png`
  return (
    <img
      src={src}
      alt={`${track} ${level}`}
      className={`${size} shrink-0 object-contain ${className}`}
      onError={(e) => { e.target.style.display = 'none' }}
    />
  )
}

export function CogAvatar({ department, type, size = 'size-7', className = '' }) {
  if (!department && !type) return null
  const src = type ? `assets/cog-${department}-${type}.png` : `assets/dept-${department}.png`
  return (
    <img
      src={src}
      alt={type || department}
      className={`${size} shrink-0 rounded-full object-cover ${className}`}
      onError={(e) => { e.target.style.display = 'none' }}
    />
  )
}

export function DeptIcon({ department, size = 'size-4', className = '' }) {
  if (!department) return null
  const src = `assets/dept-${department}.png`
  return (
    <img
      src={src}
      alt={department}
      className={`${size} shrink-0 object-contain ${className}`}
      onError={(e) => { e.target.style.display = 'none' }}
    />
  )
}
