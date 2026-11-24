import { apiFetch } from '@/services/http'

/** An owned geometry snapshot. The library list never downloads the private coordinates. */
export interface SavedRoute {
  id: number
  name: string
  activity_type: number
  point_count: number
  source_activity_id: number | null
}

export interface RouteTrip {
  id: number
  title: string
}

export const supportedRouteActivities = new Set([1, 2, 4, 5, 6, 11, 12, 27, 29, 34, 35, 36])

export function saveActivityRoute(activityId: number, name: string): Promise<SavedRoute> {
  return apiFetch('/workbench/activities/' + activityId + '/saved-route', {
    method: 'PUT',
    body: JSON.stringify({ name }),
  })
}

export function listSavedRoutes(signal?: AbortSignal): Promise<SavedRoute[]> {
  return apiFetch('/workbench/saved-routes', { signal })
}

export function listRouteTrips(signal?: AbortSignal): Promise<RouteTrip[]> {
  return apiFetch('/workbench/route-trips', { signal })
}

export function sendRouteToTrip(routeId: number, tripId: number) {
  return apiFetch<{ already_added: boolean; tour_id: number | null; sent_points: number }>(
    `/workbench/saved-routes/${routeId}/trips/${tripId}`,
    { method: 'POST' },
  )
}
