<template>
  <div class="overflow-x-auto rounded-xl">
    <table class="w-full border-collapse text-sm">
      <thead>
        <tr class="bg-surface">
          <slot name="header" />
        </tr>
      </thead>
      <tbody>
        <slot />
      </tbody>
    </table>
  </div>
</template>
