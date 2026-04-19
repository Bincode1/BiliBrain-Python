import { computed, inject, provide } from "vue"

const CONTEXT_KEY = Symbol("ai-elements-context")

export function provideContextState(props) {
  const percent = computed(() => {
    const max = Number(props.maxTokens || 0)
    const used = Number(props.usedTokens || 0)
    if (max <= 0)
      return 0
    return Math.max(0, Math.min((used / max) * 100, 100))
  })

  const state = {
    props,
    percent,
  }
  provide(CONTEXT_KEY, state)
  return state
}

export function useContextState() {
  const state = inject(CONTEXT_KEY, null)
  if (!state)
    throw new Error("Context state is missing.")
  return state
}
