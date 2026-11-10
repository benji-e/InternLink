/**
 * Flat illustrations for the "Who InternLink is for" cards on the home page.
 * Drawn inline so they load instantly and carry no image licensing.
 * To use photos instead, replace a component's <svg> with an <img>.
 */

import type { ReactNode } from 'react'

const BLUE = '#1f5fd1'
const BLUE_SOFT = '#dbe6fa'
const INK = '#1e1e1c'
const PAPER = '#ffffff'
const SKIN = '#8a5636'
const SKIN_DARK = '#6b3f26'
const HAIR = '#2a1d16'
const SUN = '#f2b84b'
const GROUND = '#e6e6e2'

function Frame({ label, children }: { label: string; children: ReactNode }) {
  return (
    <svg className="audience-art" viewBox="0 0 320 170" role="img" aria-label={label} preserveAspectRatio="xMidYMid meet">
      <rect width="320" height="170" rx="10" fill="#efefec" />
      <ellipse cx="160" cy="158" rx="130" ry="8" fill={GROUND} />
      {children}
    </svg>
  )
}

/** Home page hero: a mentor and a student at a table, looking at a matched internship together. */
export function HeroArt() {
  return (
    <svg className="hero-art" viewBox="0 0 540 330" role="img" aria-label="A mentor helping a student find an internship on a laptop" preserveAspectRatio="xMidYMid slice">
      <rect width="540" height="330" fill="#e9eef8" />
      {/* window with a city outline */}
      <rect x="320" y="34" width="176" height="120" rx="6" fill={PAPER} />
      <path d="M326 148 V118 h18 v-14 h16 v22 h14 V96 h20 v52 h12 v-30 h16 v-12 h18 v42 h16 V112 h20 v36 Z" fill={BLUE_SOFT} />
      <line x1="408" y1="34" x2="408" y2="154" stroke="#e9eef8" strokeWidth="4" />
      {/* plant */}
      <rect x="40" y="208" width="34" height="34" rx="4" fill={SUN} />
      <path d="M57 208 C40 186 34 168 46 154 C56 170 58 188 57 208 Z" fill="#2f7d4f" />
      <path d="M57 208 C70 184 82 172 92 168 C88 186 74 200 57 208 Z" fill="#3c9a62" />
      {/* floor */}
      <rect x="0" y="292" width="540" height="38" fill={GROUND} />

      {/* mentor (left) */}
      <rect x="118" y="230" width="16" height="64" rx="6" fill={INK} />
      <rect x="140" y="230" width="16" height="64" rx="6" fill={INK} />
      <path d="M106 160 Q137 136 168 160 L172 236 L102 236 Z" fill={BLUE} />
      <path d="M131 148 L137 166 L143 148 Z" fill={PAPER} />
      <circle cx="137" cy="118" r="24" fill={SKIN_DARK} />
      <path d="M113 112 Q116 90 137 90 Q159 90 161 110 Q151 102 137 102 Q122 102 113 112 Z" fill={HAIR} />
      {/* mentor arm pointing at the screen */}
      <path d="M164 178 Q196 184 222 168" stroke={SKIN_DARK} strokeWidth="13" strokeLinecap="round" fill="none" />

      {/* table */}
      <rect x="180" y="214" width="270" height="14" rx="4" fill={INK} />
      <rect x="196" y="228" width="12" height="66" fill={INK} />
      <rect x="422" y="228" width="12" height="66" fill={INK} />
      {/* laptop */}
      <rect x="222" y="122" width="132" height="88" rx="8" fill={INK} />
      <rect x="230" y="130" width="116" height="72" rx="4" fill={PAPER} />
      <rect x="210" y="208" width="156" height="8" rx="4" fill={INK} />
      {/* match card on screen */}
      <rect x="240" y="140" width="20" height="20" rx="4" fill={BLUE_SOFT} />
      <rect x="268" y="142" width="50" height="6" rx="3" fill={INK} />
      <rect x="268" y="153" width="34" height="5" rx="2.5" fill="#b9b9b3" />
      <rect x="240" y="172" width="96" height="7" rx="3.5" fill={BLUE_SOFT} />
      <rect x="240" y="172" width="70" height="7" rx="3.5" fill={BLUE} />
      <rect x="240" y="186" width="40" height="8" rx="4" fill={BLUE} />
      <circle cx="330" cy="148" r="10" fill={SUN} />
      <path d="M325 148 l3.5 3.5 l6 -7" stroke={INK} strokeWidth="2.4" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      {/* mug and notebook */}
      <rect x="384" y="194" width="20" height="20" rx="4" fill={PAPER} stroke={INK} strokeWidth="2.5" />
      <path d="M404 199 q8 0 8 6 q0 6 -8 6" stroke={INK} strokeWidth="2.5" fill="none" />
      <rect x="412" y="204" width="30" height="10" rx="2" fill={BLUE_SOFT} />

      {/* student (right) */}
      <rect x="452" y="234" width="16" height="60" rx="6" fill={INK} />
      <rect x="474" y="234" width="16" height="60" rx="6" fill={INK} />
      <path d="M438 168 Q470 146 502 168 L506 240 L434 240 Z" fill={SUN} />
      <circle cx="470" cy="126" r="24" fill={SKIN} />
      <path d="M446 124 Q444 96 470 96 Q496 96 494 124 Q492 108 470 107 Q450 108 446 124 Z" fill={HAIR} />
      <circle cx="470" cy="100" r="12" fill={HAIR} />
      {/* student arm resting on the table */}
      <path d="M442 186 Q426 204 410 210" stroke={SKIN} strokeWidth="13" strokeLinecap="round" fill="none" />
    </svg>
  )
}

/** A student with a backpack, holding a laptop that shows a matched internship. */
export function StudentArt() {
  return (
    <Frame label="A student with a laptop showing a matched internship">
      {/* backpack */}
      <rect x="92" y="70" width="34" height="50" rx="9" fill={BLUE} />
      <rect x="98" y="96" width="22" height="14" rx="4" fill="#174baa" />
      {/* legs */}
      <rect x="114" y="118" width="12" height="38" rx="5" fill={INK} />
      <rect x="132" y="118" width="12" height="38" rx="5" fill={INK} />
      <rect x="110" y="150" width="18" height="7" rx="3" fill={PAPER} stroke={INK} strokeWidth="2" />
      <rect x="130" y="150" width="18" height="7" rx="3" fill={PAPER} stroke={INK} strokeWidth="2" />
      {/* body */}
      <path d="M106 76 Q129 62 152 76 L156 122 Q129 128 104 122 Z" fill={SUN} />
      {/* head */}
      <circle cx="129" cy="50" r="17" fill={SKIN} />
      <path d="M112 47 Q114 30 130 30 Q146 30 147 46 Q140 39 129 40 Q118 40 112 47 Z" fill={HAIR} />
      {/* arm holding laptop */}
      <path d="M150 84 Q166 92 176 100" stroke={SKIN} strokeWidth="9" strokeLinecap="round" fill="none" />
      {/* laptop */}
      <rect x="168" y="66" width="86" height="56" rx="6" fill={INK} />
      <rect x="173" y="71" width="76" height="46" rx="3" fill={PAPER} />
      <rect x="160" y="121" width="102" height="6" rx="3" fill={INK} />
      {/* match card on screen */}
      <rect x="179" y="77" width="14" height="14" rx="3" fill={BLUE_SOFT} />
      <rect x="198" y="78" width="38" height="5" rx="2.5" fill={INK} />
      <rect x="198" y="87" width="26" height="4" rx="2" fill="#b9b9b3" />
      <rect x="179" y="99" width="64" height="5" rx="2.5" fill={BLUE_SOFT} />
      <rect x="179" y="99" width="46" height="5" rx="2.5" fill={BLUE} />
      <circle cx="240" cy="83" r="7" fill={BLUE} />
      <path d="M236.5 83 l2.5 2.5 l4.5 -5" stroke={PAPER} strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
    </Frame>
  )
}

/** An employer at a desk reviewing applicant cards, one marked as a match. */
export function EmployerArt() {
  return (
    <Frame label="An employer at a desk reviewing applicants">
      {/* window */}
      <rect x="200" y="22" width="78" height="56" rx="4" fill={PAPER} stroke="#cfcfca" strokeWidth="2" />
      <line x1="239" y1="22" x2="239" y2="78" stroke="#cfcfca" strokeWidth="2" />
      <line x1="200" y1="50" x2="278" y2="50" stroke="#cfcfca" strokeWidth="2" />
      {/* person */}
      <path d="M58 96 Q82 80 106 96 L108 128 L56 128 Z" fill={BLUE} />
      <path d="M78 84 L82 98 L86 84 Z" fill={PAPER} />
      <circle cx="82" cy="66" r="16" fill={SKIN_DARK} />
      <path d="M66 63 Q68 48 82 48 Q97 48 98 62 Q92 56 82 56 Q72 56 66 63 Z" fill={HAIR} />
      <path d="M104 104 Q122 108 134 104" stroke={SKIN_DARK} strokeWidth="8" strokeLinecap="round" fill="none" />
      {/* desk */}
      <rect x="40" y="118" width="244" height="10" rx="3" fill={INK} />
      <rect x="52" y="128" width="8" height="28" fill={INK} />
      <rect x="264" y="128" width="8" height="28" fill={INK} />
      {/* applicant cards */}
      <rect x="132" y="86" width="44" height="30" rx="4" fill={PAPER} stroke="#cfcfca" strokeWidth="2" />
      <circle cx="143" cy="97" r="5" fill={GROUND} />
      <rect x="151" y="93" width="19" height="4" rx="2" fill="#b9b9b3" />
      <rect x="151" y="100" width="13" height="4" rx="2" fill={GROUND} />
      <rect x="184" y="80" width="50" height="36" rx="4" fill={PAPER} stroke={BLUE} strokeWidth="2.5" />
      <circle cx="197" cy="93" r="6" fill={BLUE_SOFT} />
      <rect x="207" y="89" width="21" height="4" rx="2" fill={INK} />
      <rect x="207" y="96" width="15" height="4" rx="2" fill="#b9b9b3" />
      <rect x="190" y="106" width="38" height="4" rx="2" fill={BLUE} />
      <circle cx="232" cy="80" r="8" fill={SUN} />
      <path d="M228 80 l3 3 l5 -6" stroke={INK} strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round" />
      {/* mug */}
      <rect x="246" y="102" width="14" height="16" rx="3" fill={SUN} />
      <path d="M260 106 q6 0 6 5 q0 5 -6 5" stroke={SUN} strokeWidth="3" fill="none" />
    </Frame>
  )
}

/** A university building with a coordinator holding a list of verified students. */
export function UniversityArt() {
  return (
    <Frame label="A university coordinator verifying students">
      {/* building */}
      <path d="M150 50 L230 22 L310 50 Z" fill={INK} />
      <rect x="156" y="50" width="148" height="8" fill={INK} />
      {[166, 194, 222, 250, 278].map((x) => <rect key={x} x={x} y="62" width="12" height="80" fill={PAPER} stroke="#cfcfca" strokeWidth="2" />)}
      <rect x="150" y="142" width="160" height="12" rx="2" fill={INK} />
      <circle cx="230" cy="38" r="5" fill={SUN} />
      {/* coordinator */}
      <path d="M44 92 Q70 76 96 92 L100 128 L42 128 Z" fill={SUN} />
      <rect x="54" y="126" width="12" height="30" rx="5" fill={INK} />
      <rect x="74" y="126" width="12" height="30" rx="5" fill={INK} />
      <circle cx="70" cy="62" r="16" fill={SKIN} />
      <path d="M53 62 Q52 42 70 42 Q88 42 87 62 Q86 52 70 51 Q56 52 53 62 Z" fill={HAIR} />
      <circle cx="70" cy="46" r="9" fill={HAIR} />
      {/* clipboard */}
      <rect x="96" y="78" width="46" height="60" rx="5" fill={BLUE} />
      <rect x="101" y="86" width="36" height="47" rx="3" fill={PAPER} />
      <rect x="111" y="74" width="16" height="8" rx="3" fill={INK} />
      {[94, 106, 118].map((y) => (
        <g key={y}>
          <circle cx="108" cy={y} r="4" fill={BLUE_SOFT} />
          <path d={`M106 ${y} l1.6 1.6 l3 -3.4`} stroke={BLUE} strokeWidth="1.8" fill="none" strokeLinecap="round" strokeLinejoin="round" />
          <rect x="115" y={y - 2} width="17" height="4" rx="2" fill="#b9b9b3" />
        </g>
      ))}
      <path d="M94 100 Q100 104 104 106" stroke={SKIN} strokeWidth="8" strokeLinecap="round" fill="none" />
    </Frame>
  )
}
