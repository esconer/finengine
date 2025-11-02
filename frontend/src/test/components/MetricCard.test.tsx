import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MetricCard } from '@/components/ui/MetricCard'
import type { MetricCardProps } from '@/components/ui/MetricCard'
import { TrendingUp, TrendingDown, Minus } from 'lucide-react'

// Mock data factory
const createMockMetricCard = (props: Partial<MetricCardProps> = {}): MetricCardProps => ({
    title: 'Test Metric',
    value: 100,
    ...props
})

describe('MetricCard', () => {
    beforeEach(() => {
        vi.clearAllMocks()
    })

    describe('Rendering', () => {
        it('should render metric card with basic props', () => {
            const props = createMockMetricCard()
            render(<MetricCard {...props} />)

            expect(screen.getByText('Test Metric')).toBeInTheDocument()
            expect(screen.getByText('100.00')).toBeInTheDocument()
        })

        it('should render with string value', () => {
            const props = createMockMetricCard({
                value: '1,234.56'
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('1,234.56')).toBeInTheDocument()
        })

        it('should render with positive change', () => {
            const props = createMockMetricCard({
                change: 5.2,
                changeType: 'positive'
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('+5.20%')).toBeInTheDocument()
            expect(screen.getByText('+5.20%')).toHaveClass('text-green-600', 'dark:text-green-400')
        })

        it('should render with negative change', () => {
            const props = createMockMetricCard({
                change: -2.1,
                changeType: 'negative'
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('-2.10%')).toBeInTheDocument()
            expect(screen.getByText('-2.10%')).toHaveClass('text-red-600', 'dark:text-red-400')
        })

        it('should render with neutral change', () => {
            const props = createMockMetricCard({
                change: 0,
                changeType: 'neutral'
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('+0.00%')).toBeInTheDocument()
            expect(screen.getByText('+0.00%')).toHaveClass('text-gray-600', 'dark:text-gray-400')
        })

        it('should render with custom icon', () => {
            const props = createMockMetricCard({
                icon: TrendingUp
            })
            render(<MetricCard {...props} />)

            expect(screen.getByTestId('metric-card')).toBeInTheDocument()
            // Check that the icon is rendered (checking for lucide-react icon)
            const iconElements = screen.getByTestId('metric-card').querySelectorAll('svg')
            expect(iconElements.length).toBeGreaterThan(0)
        })

        it('should render loading state', () => {
            const props = createMockMetricCard({
                loading: true
            })
            render(<MetricCard {...props} />)

            // Check for loading animation elements
            expect(screen.getByTestId('metric-card')).toBeInTheDocument()
            const loadingElements = screen.getAllByText('1')
            expect(loadingElements.length).toBeGreaterThan(0)
        })

        it('should not render change when change is undefined', () => {
            const props = createMockMetricCard({
                change: undefined
            })
            render(<MetricCard {...props} />)

            expect(screen.queryByText('%')).not.toBeInTheDocument()
        })
    })

    describe('Value Formatting', () => {
        it('should format large numbers with K suffix', () => {
            const props = createMockMetricCard({
                value: 1234.56
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('$1.2K')).toBeInTheDocument()
        })

        it('should format large numbers with M suffix', () => {
            const props = createMockMetricCard({
                value: 1234567.89
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('$1.2M')).toBeInTheDocument()
        })

        it('should format small numbers with decimal places', () => {
            const props = createMockMetricCard({
                value: 123.456789
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('123.46')).toBeInTheDocument()
        })

        it('should handle string values directly', () => {
            const props = createMockMetricCard({
                value: 'N/A'
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('N/A')).toBeInTheDocument()
        })
    })

    describe('Change Formatting', () => {
        it('should format positive changes with + sign', () => {
            const props = createMockMetricCard({
                change: 10.5
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('+10.50%')).toBeInTheDocument()
        })

        it('should format negative changes without double negative', () => {
            const props = createMockMetricCard({
                change: -10.5,
                changeType: 'negative'
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('-10.50%')).toBeInTheDocument()
        })

        it('should format zero change with + sign', () => {
            const props = createMockMetricCard({
                change: 0
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('+0.00%')).toBeInTheDocument()
        })
    })

    describe('Styling and Classes', () => {
        it('should apply custom className', () => {
            const props = createMockMetricCard({
                className: 'custom-class'
            })
            render(<MetricCard {...props} />)

            expect(screen.getByTestId('metric-card')).toHaveClass('custom-class')
        })

        it('should apply positive change styling', () => {
            const props = createMockMetricCard({
                change: 5.0,
                changeType: 'positive'
            })
            render(<MetricCard {...props} />)

            const changeElement = screen.getByText('+5.00%')
            expect(changeElement).toHaveClass('bg-green-100', 'dark:bg-green-900/20')
            expect(changeElement).toHaveClass('text-green-600', 'dark:text-green-400')
        })

        it('should apply negative change styling', () => {
            const props = createMockMetricCard({
                change: -5.0,
                changeType: 'negative'
            })
            render(<MetricCard {...props} />)

            const changeElement = screen.getByText('-5.00%')
            expect(changeElement).toHaveClass('bg-red-100', 'dark:bg-red-900/20')
            expect(changeElement).toHaveClass('text-red-600', 'dark:text-red-400')
        })

        it('should apply neutral change styling', () => {
            const props = createMockMetricCard({
                change: 0,
                changeType: 'neutral'
            })
            render(<MetricCard {...props} />)

            const changeElement = screen.getByText('+0.00%')
            expect(changeElement).toHaveClass('bg-gray-100', 'dark:bg-gray-800')
            expect(changeElement).toHaveClass('text-gray-600', 'dark:text-gray-400')
        })
    })

    describe('Loading State', () => {
        it('should show loading animation when loading is true', () => {
            const props = createMockMetricCard({
                loading: true
            })
            render(<MetricCard {...props} />)

            const card = screen.getByTestId('metric-card')
            expect(card).toBeInTheDocument()
            // Check for loading animation classes
            expect(card.querySelector('.animate-pulse')).toBeInTheDocument()
        })

        it('should not show value when loading', () => {
            const props = createMockMetricCard({
                value: 100,
                loading: true
            })
            render(<MetricCard {...props} />)

            expect(screen.queryByText('100.00')).not.toBeInTheDocument()
        })

        it('should show skeleton placeholders when loading', () => {
            const props = createMockMetricCard({
                loading: true
            })
            render(<MetricCard {...props} />)

            // Check for skeleton animation elements
            const card = screen.getByTestId('metric-card')
            const skeletonElements = card.querySelectorAll('.animate-pulse div')
            expect(skeletonElements.length).toBeGreaterThan(0)
        })
    })

    describe('Icon Handling', () => {
        it('should render icon when provided', () => {
            const props = createMockMetricCard({
                icon: TrendingUp
            })
            render(<MetricCard {...props} />)

            const card = screen.getByTestId('metric-card')
            const iconElements = card.querySelectorAll('svg')
            expect(iconElements.length).toBeGreaterThan(0)
        })

        it('should not render icon when not provided', () => {
            const props = createMockMetricCard({
                icon: undefined
            })
            render(<MetricCard {...props} />)

            const card = screen.getByTestId('metric-card')
            const iconElements = card.querySelectorAll('svg')
            expect(iconElements.length).toBe(0)
        })

        it('should render different icons correctly', () => {
            const { rerender } = render(<MetricCard {...createMockMetricCard({ icon: TrendingUp })} />)

            let card = screen.getByTestId('metric-card')
            expect(card.querySelectorAll('svg').length).toBeGreaterThan(0)

            rerender(<MetricCard {...createMockMetricCard({ icon: TrendingDown })} />)
            card = screen.getByTestId('metric-card')
            expect(card.querySelectorAll('svg').length).toBeGreaterThan(0)

            rerender(<MetricCard {...createMockMetricCard({ icon: Minus })} />)
            card = screen.getByTestId('metric-card')
            expect(card.querySelectorAll('svg').length).toBeGreaterThan(0)
        })
    })

    describe('Edge Cases', () => {
        it('should handle very large numbers', () => {
            const props = createMockMetricCard({
                value: 999999999999
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('$1000000.0M')).toBeInTheDocument()
        })

        it('should handle negative numbers', () => {
            const props = createMockMetricCard({
                value: -123.45
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('-123.45')).toBeInTheDocument()
        })

        it('should handle zero value', () => {
            const props = createMockMetricCard({
                value: 0
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('0.00')).toBeInTheDocument()
        })

        it('should handle very small decimal numbers', () => {
            const props = createMockMetricCard({
                value: 0.001
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('0.00')).toBeInTheDocument()
        })

        it('should handle extreme change values', () => {
            const props = createMockMetricCard({
                change: 999.99,
                changeType: 'positive'
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('+999.99%')).toBeInTheDocument()
        })

        it('should handle empty string value', () => {
            const props = createMockMetricCard({
                value: ''
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('')).toBeInTheDocument()
        })
    })

    describe('Accessibility', () => {
        it('should render with proper semantic structure', () => {
            const props = createMockMetricCard()
            render(<MetricCard {...props} />)

            const card = screen.getByTestId('metric-card')
            expect(card.tagName).toBe('DIV')

            const title = screen.getByText('Test Metric')
            expect(title.tagName).toBe('H3')

            const value = screen.getByText('100.00')
            expect(value.tagName).toBe('P')
        })

        it('should have proper text content for screen readers', () => {
            const props = createMockMetricCard({
                title: 'Portfolio Value',
                value: 1234567.89
            })
            render(<MetricCard {...props} />)

            expect(screen.getByText('Portfolio Value')).toBeInTheDocument()
            expect(screen.getByText('$1.2M')).toBeInTheDocument()
        })
    })

    describe('Performance', () => {
        it('should not cause re-render issues with rapid prop changes', () => {
            const props = createMockMetricCard()
            const { rerender } = render(<MetricCard {...props} />)

            // Rapid prop changes
            for (let i = 0; i < 10; i++) {
                rerender(<MetricCard {...props} value={i} />)
            }

            expect(screen.getByText('9.00')).toBeInTheDocument()
        })

        it('should handle many re-renders efficiently', () => {
            const props = createMockMetricCard()
            const { rerender } = render(<MetricCard {...props} />)

            // Simulate rapid state updates
            for (let i = 0; i < 100; i++) {
                rerender(<MetricCard {...props} value={i} change={i - 50} changeType={i > 50 ? 'positive' : 'negative'} />)
            }

            const value = screen.getByText('99.00')
            expect(value).toBeInTheDocument()
        })
    })
})