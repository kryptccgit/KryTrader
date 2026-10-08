export const ONBOARDING_REVISION = 2;

export function autoOnboarding(
  state: { acceptedDisclaimer: boolean; onboardingSeen?: number } | null | undefined,
): 'first' | 'update' | null {
  if (!state) return null;
  if (!state.acceptedDisclaimer) return 'first';
  return (state.onboardingSeen ?? 0) < ONBOARDING_REVISION ? 'update' : null;
}
