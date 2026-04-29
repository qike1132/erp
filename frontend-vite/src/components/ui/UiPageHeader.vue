<template>
  <div class="mb-5">
    <h2 class="text-xl font-bold text-text mb-1">
      <slot />
    </h2>
    <p v-if="$slots.description" class="text-sm text-text-secondary">
      <slot name="description" />
    </p>
  </div>
</template>
