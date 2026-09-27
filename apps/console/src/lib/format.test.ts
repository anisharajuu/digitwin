import { describe, expect, it } from 'vitest'

import { duration, eur, healthColour, num, pct, simClock, titleCase } from './format'

describe('duration', () => {
  it('reads the way an engineer says it out loud', () => {
    // "4,380 h" tells nobody anything; the unit has to change with the scale.
    expect(duration(0.5)).toBe('30 min')
    expect(duration(23)).toBe('23.0 h')
    expect(duration(72)).toBe('3.0 d')
    expect(duration(24 * 90)).toBe('3.0 mo')
  })

  it('says "stable" rather than inventing a date for a mode that is not trending', () => {
    expect(duration(null)).toBe('stable')
    expect(duration(undefined)).toBe('stable')
  })

  it('switches units at the documented boundaries', () => {
    expect(duration(47.9)).toContain('h')
    expect(duration(48)).toContain('d')
    expect(duration(24 * 59)).toContain('d')
    expect(duration(24 * 60)).toContain('mo')
  })
})

describe('num and pct', () => {
  it('renders missing values as a dash rather than NaN', () => {
    expect(num(null)).toBe('--')
    expect(num(undefined)).toBe('--')
    expect(num(Number.NaN)).toBe('--')
    expect(pct(null)).toBe('--')
  })

  it('honours the requested precision', () => {
    expect(num(3.14159, 2)).toBe('3.14')
    expect(num(3.14159, 0)).toBe('3')
    expect(pct(0.8213)).toBe('82.1%')
  })
})

describe('eur', () => {
  it('compacts only large values, and only when asked', () => {
    expect(eur(8900)).toBe('€8,900')
    expect(eur(8900, true)).toBe('€8,900')
    // Intl's compact suffix is case-inconsistent across ICU builds - macOS
    // renders "41K", Linux "41k" - so assert the shape, not the casing.
    expect(eur(41000, true)).toMatch(/^€41[kK]$/)
  })

  it('never shows fractional euros', () => {
    expect(eur(8900.62)).toBe('€8,901')
  })
})

describe('simClock', () => {
  it('drops the day field until there is a day to show', () => {
    expect(simClock(3600 * 5 + 120)).toBe('5h 02m')
    expect(simClock(86400 + 3600 * 2)).toBe('1d 2h 00m')
  })
})

describe('healthColour', () => {
  it('is monotonic: worse health never returns a calmer colour', () => {
    const ramp = [100, 85, 70, 50, 30, 10].map(healthColour)
    expect(new Set(ramp).size).toBeGreaterThan(3)
    expect(healthColour(95)).toBe(healthColour(80))
    expect(healthColour(79)).not.toBe(healthColour(80))
    expect(healthColour(10)).toBe('#fb7185')
  })
})

describe('titleCase', () => {
  it('turns a degradation mode key into a label', () => {
    expect(titleCase('impeller_wear')).toBe('Impeller Wear')
    expect(titleCase('lubricant_degradation')).toBe('Lubricant Degradation')
  })
})
