/* eslint-disable @typescript-eslint/no-explicit-any */
import { render, screen, fireEvent } from '@testing-library/react'
import { describe, it, expect, vi } from 'vitest'
import { AppSidebar } from './AppSidebar'
import { useSidebarStore } from '@/lib/stores/sidebar-store'
import { useDeveloperStore } from '@/lib/stores/developer-store'

// Mock Tooltip components to avoid Radix UI async issues in tests
vi.mock('@/components/ui/tooltip', () => ({
  TooltipProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  Tooltip: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipTrigger: ({ children }: { children: React.ReactNode }) => <>{children}</>,
  TooltipContent: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

describe('AppSidebar', () => {
  it('renders correctly when expanded', () => {
    render(<AppSidebar />)

    // With mocked t() returning keys, check for translation key strings
    expect(screen.getByText('common.appName')).toBeDefined()
    expect(screen.getByText('navigation.sources')).toBeDefined()
    expect(screen.getByText('navigation.notebooks')).toBeDefined()
  })

  it('toggles collapse state when clicking handle', () => {
    const toggleCollapse = vi.fn()
    vi.mocked(useSidebarStore).mockReturnValue({
      isCollapsed: false,
      toggleCollapse,
    } as any)

    render(<AppSidebar />)

    fireEvent.click(screen.getByTestId('sidebar-toggle'))

    expect(toggleCollapse).toHaveBeenCalled()
  })

  it('shows collapsed view when isCollapsed is true', () => {
    vi.mocked(useSidebarStore).mockReturnValue({
      isCollapsed: true,
      toggleCollapse: vi.fn(),
    } as any)

    render(<AppSidebar />)

    // In collapsed mode, app name shouldn't be visible (as text)
    expect(screen.queryByText('common.appName')).toBeNull()
  })

  it('hides manage section when developer mode is off', () => {
    vi.mocked(useDeveloperStore).mockReturnValue({
      isDeveloperMode: false,
      toggleDeveloperMode: vi.fn(),
      setDeveloperMode: vi.fn(),
    } as any)

    render(<AppSidebar />)

    // Manage section items should not be visible
    expect(screen.queryByText('navigation.models')).toBeNull()
    expect(screen.queryByText('navigation.settings')).toBeNull()
  })

  it('shows manage section when developer mode is on', () => {
    vi.mocked(useDeveloperStore).mockReturnValue({
      isDeveloperMode: true,
      toggleDeveloperMode: vi.fn(),
      setDeveloperMode: vi.fn(),
    } as any)

    render(<AppSidebar />)

    // Manage section items should be visible
    expect(screen.getByText('navigation.models')).toBeDefined()
    expect(screen.getByText('navigation.settings')).toBeDefined()
  })
})
