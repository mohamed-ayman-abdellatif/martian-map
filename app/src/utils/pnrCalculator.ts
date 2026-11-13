import type { MissionParams, RouteBundle, WaypointProfile } from '../types/contracts';

export interface EvaluatedRoute {
  pnrIdx: number;
  pnrWaypoint: WaypointProfile;
  goalReachableWithinReserve: boolean;
  usableBudget: number;
  totalBudget: number;
  budgetUnit: 'L O₂' | 'min';
  outboundO2PerSuit: number;
  returnO2PerSuit: number;
  totalRoundTripO2PerSuit: number;
  totalCrewO2: number;
  outboundTimeMin: number;
  returnTimeMin: number;
  totalRoundTripTimeMin: number;
  scaledUsed: number[];
  scaledBack: number[];
  scaledO2Remaining: number[];
  loadRescaled: boolean;
}

/**
 * Compute <1ms client-side consumables & Turn-Back (PNR) evaluation from precomputed
 * forward & backward-Dijkstra fields stored in waypoints_profile.
 */
export function evaluateMissionRoute(route: RouteBundle, params: MissionParams): EvaluatedRoute {
  const wps = route.waypoints_profile;
  // Pandolf carried-load scaling ratio relative to engine reference (W=80 kg, L_ref=30 kg)
  const loadFactor = (80 + params.loadKg) / 110;
  const o2Scale = params.kappa * loadFactor;
  const crewCount = params.crewMode === 'buddy' ? 2 : 1;

  const isO2 = params.budgetType === 'o2';
  const totalBudget = isO2 ? params.o2BudgetLiters : params.timeBudgetHours * 60;
  const usableBudget = (1 - params.reserveFraction) * totalBudget;

  const scaledUsed: number[] = [];
  const scaledBack: number[] = [];
  const scaledO2Remaining: number[] = [];

  for (const w of wps) {
    if (isO2) {
      const u = w.used_o2_l_base * o2Scale;
      const b = w.back_o2_l_base * o2Scale;
      scaledUsed.push(u);
      scaledBack.push(b);
      scaledO2Remaining.push(Math.max(0, params.o2BudgetLiters - u));
    } else {
      const u = w.used_time_s / 60;
      const b = w.back_time_s / 60;
      scaledUsed.push(u);
      scaledBack.push(b);
      const o2u = w.used_o2_l_base * o2Scale;
      scaledO2Remaining.push(Math.max(0, params.o2BudgetLiters - o2u));
    }
  }

  let pnrIdx = 0;
  for (let i = 0; i < wps.length; i++) {
    if (scaledUsed[i] + scaledBack[i] <= usableBudget + 1e-6) {
      pnrIdx = i;
    } else {
      break;
    }
  }

  const last = wps[wps.length - 1];
  const outboundO2PerSuit = last.used_o2_l_base * o2Scale;
  const returnO2PerSuit = last.back_o2_l_base * o2Scale;
  const totalRoundTripO2PerSuit = outboundO2PerSuit + returnO2PerSuit;
  const outboundTimeMin = last.used_time_s / 60;
  const returnTimeMin = last.back_time_s / 60;

  return {
    pnrIdx,
    pnrWaypoint: wps[pnrIdx],
    goalReachableWithinReserve: pnrIdx === wps.length - 1,
    usableBudget,
    totalBudget,
    budgetUnit: isO2 ? 'L O₂' : 'min',
    outboundO2PerSuit,
    returnO2PerSuit,
    totalRoundTripO2PerSuit,
    totalCrewO2: totalRoundTripO2PerSuit * crewCount,
    outboundTimeMin,
    returnTimeMin,
    totalRoundTripTimeMin: outboundTimeMin + returnTimeMin,
    scaledUsed,
    scaledBack,
    scaledO2Remaining,
    loadRescaled: Math.abs(params.loadKg - 30) > 0.1,
  };
}
