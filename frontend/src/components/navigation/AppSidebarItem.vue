<template>
  <RouterLink
    :class="['app-sidebar-item', `app-sidebar-item-${item.id}`, { active: isActive }]"
    :to="item.path"
    :title="item.description"
  >
    <span class="app-sidebar-item-icon" aria-hidden="true">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">
        <path v-for="path in itemIcon.paths" :key="path" :d="path" />
      </svg>
    </span>
    <strong>{{ item.name }}</strong>
  </RouterLink>
</template>

<script setup>
import { computed } from "vue";
import { useRoute, RouterLink } from "vue-router";

const props = defineProps({
  item: {
    type: Object,
    required: true,
  },
});

const route = useRoute();
const isActive = computed(() => route.name === props.item.routeName);
const itemIcon = computed(() => {
  const iconMap = {
    chat: {
      paths: [
        "M5.5 5.5h13a1.5 1.5 0 0 1 1.5 1.5v8a1.5 1.5 0 0 1-1.5 1.5H10l-4.5 3v-3H5.5A1.5 1.5 0 0 1 4 15V7a1.5 1.5 0 0 1 1.5-1.5Z",
        "M8 10h8",
        "M8 13h5",
      ],
    },
    library: {
      paths: [
        "M4.5 6.5A1.5 1.5 0 0 1 6 5h4l1.6 1.8H18A1.5 1.5 0 0 1 19.5 8.3v8.2A1.5 1.5 0 0 1 18 18H6a1.5 1.5 0 0 1-1.5-1.5v-10Z",
        "M4.5 9h15",
      ],
    },
    "skills-store": {
      paths: [
        "m12 3 1.4 3.4L17 7.8l-2.7 2.4.8 3.5L12 12.1 8.9 13.7l.8-3.5L7 7.8l3.6-1.4L12 3Z",
        "M18.5 14.5 20 18l-3.2-1.2L14.5 18l1.3-3.5",
      ],
    },
    "tools-store": {
      paths: [
        "M14.7 6.3a3.2 3.2 0 0 0 4.5 4.5l-4.8 4.8a2.5 2.5 0 1 1-3.5-3.5Z",
        "m13 8-5.5 5.5",
        "m5 19 1.5-1.5",
      ],
    },
  };
  return iconMap[props.item.id] || {
    paths: [
      "M12 5.5a6.5 6.5 0 1 1 0 13 6.5 6.5 0 0 1 0-13Z",
    ],
  };
});
</script>
