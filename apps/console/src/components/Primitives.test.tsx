import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { HealthBar, Sparkline, StateChip } from './Primitives'

describe('Sparkline', () => {
  it('renders nothing meaningful below two points instead of drawing a broken path', () => {
    const { container } = render(<Sparkline values={[]} />)
    expect(container.querySelector('path')).toBeNull()
  })

  it('does not divide by zero on a flat series', () => {
    // A KPI that has not moved yet gives min === max; without the guard the
    // path fills with NaN and the whole tile disappears.
    const { container } = render(<Sparkline values={[42, 42, 42, 42]} />)
    const paths = [...container.querySelectorAll('path')]
    expect(paths.length).toBeGreaterThan(0)
    for (const path of paths) {
      expect(path.getAttribute('d')).not.toContain('NaN')
    }
  })

  it('draws a point per sample', () => {
    const { container } = render(<Sparkline values={[1, 5, 3, 9]} />)
    const line = container.querySelectorAll('path')[1]?.getAttribute('d') ?? ''
    expect(line.match(/[ML]/g)).toHaveLength(4)
  })
})

describe('HealthBar', () => {
  const fillOf = (container: HTMLElement) =>
    [...container.querySelectorAll<HTMLElement>('div')].find((el) => el.style.width !== '')

  it('keeps a sliver of bar visible at zero, so the row still reads as a row', () => {
    const { container } = render(<HealthBar health={0} />)
    expect(fillOf(container)?.style.width).toBe('2%')
  })

  it('scales the bar with health above that floor', () => {
    const { container } = render(<HealthBar health={64} />)
    expect(fillOf(container)?.style.width).toBe('64%')
  })

  it('shows the rounded value alongside the bar', () => {
    render(<HealthBar health={83.7} />)
    expect(screen.getByText('84')).toBeInTheDocument()
  })
})

describe('StateChip', () => {
  it('labels each asset state in words rather than leaking the enum', () => {
    render(<StateChip state="maintenance" />)
    expect(screen.getByText('Maintenance')).toBeInTheDocument()
  })
})
