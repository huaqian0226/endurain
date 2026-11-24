import type { Gear } from '@/features/gears/types'

/**
 * A collapsible gear group rendered on the gears list page.
 *
 * @property name - Trimmed display name of the group.
 * @property gears - Visible gears belonging to this group, preserving input order.
 * @property totalDistanceMeters - Summed total distance across visible members, in metres.
 */
export interface GearGroupSection {
  name: string
  gears: Gear[]
  totalDistanceMeters: number
}

/**
 * Result of splitting a visible gear list into named groups and ungrouped items.
 *
 * @property groups - Named groups sorted alphabetically by group name.
 * @property ungrouped - Gears with no `groupName`, preserving input order.
 */
export interface PartitionedGears {
  groups: GearGroupSection[]
  ungrouped: Gear[]
}

/**
 * Resolves a gear's total distance in metres from list data: prefers the
 * server-computed `totalDistance`, falling back to `initialKms * 1000`.
 *
 * @param gear - The gear record.
 * @returns Non-negative total distance in metres.
 */
export function gearDistanceMeters(gear: Gear): number {
  if (gear.totalDistance !== null && Number.isFinite(gear.totalDistance)) {
    return Math.max(0, gear.totalDistance)
  }
  if (gear.initialKms !== null && Number.isFinite(gear.initialKms)) {
    return Math.max(0, gear.initialKms * 1000)
  }
  return 0
}

/**
 * Partitions a list of visible gears into named collapsible groups and a flat
 * ungrouped list. Empty groups are never emitted, and each group's total
 * distance reflects only the visible gears passed in.
 *
 * @param gears - Visible gears (already filtered by search / active status).
 * @returns Named groups (sorted by name) and ungrouped gears.
 */
export function partitionGearsByGroup(gears: readonly Gear[]): PartitionedGears {
  const byName = new Map<string, GearGroupSection>()
  const ungrouped: Gear[] = []

  for (const gear of gears) {
    const trimmed = gear.groupName?.trim() ?? ''
    if (!trimmed) {
      ungrouped.push(gear)
      continue
    }
    const existing = byName.get(trimmed)
    const distance = gearDistanceMeters(gear)
    if (existing) {
      existing.gears.push(gear)
      existing.totalDistanceMeters += distance
    } else {
      byName.set(trimmed, {
        name: trimmed,
        gears: [gear],
        totalDistanceMeters: distance,
      })
    }
  }

  const groups = Array.from(byName.values()).sort((a, b) => a.name.localeCompare(b.name))
  return { groups, ungrouped }
}

/**
 * Collects distinct non-empty gear group names, sorted for `<datalist>` options.
 *
 * @param gears - Known gears to extract group names from.
 * @returns Sorted unique group names.
 */
export function collectDistinctGroupNames(gears: readonly Gear[]): string[] {
  const seen = new Set<string>()
  for (const gear of gears) {
    const trimmed = gear.groupName?.trim() ?? ''
    if (trimmed) {
      seen.add(trimmed)
    }
  }
  return Array.from(seen).sort((a, b) => a.localeCompare(b))
}
