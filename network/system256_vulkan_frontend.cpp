#define WIN32_LEAN_AND_MEAN
#define VK_USE_PLATFORM_WIN32_KHR

#include <windows.h>
#include <vulkan/vulkan.h>
#include "libretro.h"
#include "libretro_vulkan.h"

#include <algorithm>
#include <array>
#include <cstddef>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <mutex>
#include <new>
#include <string>
#include <vector>

namespace {

constexpr unsigned kFramesInFlight = 3;

void set_error(char *out, size_t cap, const char *message)
{
   if (out && cap)
   {
      std::snprintf(out, cap, "%s", message ? message : "Unknown Vulkan error");
      out[cap - 1] = '\0';
   }
}

template <typename T>
T load_instance_function(PFN_vkGetInstanceProcAddr gipa, VkInstance instance, const char *name)
{
   return reinterpret_cast<T>(gipa(instance, name));
}

struct VulkanCore
{
   HMODULE loader = nullptr;
   PFN_vkGetInstanceProcAddr gipa = nullptr;
   PFN_vkCreateInstance create_instance = nullptr;
   PFN_vkDestroyInstance destroy_instance = nullptr;
   PFN_vkEnumeratePhysicalDevices enumerate_physical_devices = nullptr;
   PFN_vkGetPhysicalDeviceProperties get_physical_device_properties = nullptr;
   PFN_vkGetPhysicalDeviceQueueFamilyProperties get_queue_family_properties = nullptr;
   PFN_vkGetPhysicalDeviceMemoryProperties get_memory_properties = nullptr;
   PFN_vkGetDeviceProcAddr gdpa = nullptr;
   PFN_vkCreateWin32SurfaceKHR create_win32_surface = nullptr;
   PFN_vkDestroySurfaceKHR destroy_surface = nullptr;
   PFN_vkGetPhysicalDeviceSurfaceSupportKHR get_surface_support = nullptr;
   PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR get_surface_capabilities = nullptr;
   PFN_vkGetPhysicalDeviceSurfaceFormatsKHR get_surface_formats = nullptr;
   PFN_vkGetPhysicalDeviceSurfacePresentModesKHR get_surface_present_modes = nullptr;

   VkInstance instance = VK_NULL_HANDLE;
   VkPhysicalDevice gpu = VK_NULL_HANDLE;
   VkDevice device = VK_NULL_HANDLE;
   VkQueue queue = VK_NULL_HANDLE;
   VkSurfaceKHR surface = VK_NULL_HANDLE;
   VkSwapchainKHR swapchain = VK_NULL_HANDLE;
   VkFormat swapchain_format = VK_FORMAT_UNDEFINED;
   VkExtent2D swapchain_extent{};
   uint32_t queue_family = 0;
   PFN_vkDestroyDevice destroy_device = nullptr;

   PFN_vkCreateCommandPool create_command_pool = nullptr;
   PFN_vkDestroyCommandPool destroy_command_pool = nullptr;
   PFN_vkAllocateCommandBuffers allocate_command_buffers = nullptr;
   PFN_vkResetCommandBuffer reset_command_buffer = nullptr;
   PFN_vkBeginCommandBuffer begin_command_buffer = nullptr;
   PFN_vkEndCommandBuffer end_command_buffer = nullptr;
   PFN_vkCreateFence create_fence = nullptr;
   PFN_vkDestroyFence destroy_fence = nullptr;
   PFN_vkWaitForFences wait_for_fences = nullptr;
   PFN_vkResetFences reset_fences = nullptr;
   PFN_vkQueueSubmit queue_submit = nullptr;
   PFN_vkQueueWaitIdle queue_wait_idle = nullptr;
   PFN_vkDeviceWaitIdle device_wait_idle = nullptr;
   PFN_vkCreateSwapchainKHR create_swapchain = nullptr;
   PFN_vkDestroySwapchainKHR destroy_swapchain = nullptr;
   PFN_vkGetSwapchainImagesKHR get_swapchain_images = nullptr;
   PFN_vkAcquireNextImageKHR acquire_next_image = nullptr;
   PFN_vkQueuePresentKHR queue_present = nullptr;
   PFN_vkCmdBlitImage cmd_blit_image = nullptr;
   PFN_vkCreateSemaphore create_semaphore = nullptr;
   PFN_vkDestroySemaphore destroy_semaphore = nullptr;
   PFN_vkCreateBuffer create_buffer = nullptr;
   PFN_vkDestroyBuffer destroy_buffer = nullptr;
   PFN_vkGetBufferMemoryRequirements get_buffer_memory_requirements = nullptr;
   PFN_vkAllocateMemory allocate_memory = nullptr;
   PFN_vkFreeMemory free_memory = nullptr;
   PFN_vkBindBufferMemory bind_buffer_memory = nullptr;
   PFN_vkMapMemory map_memory = nullptr;
   PFN_vkUnmapMemory unmap_memory = nullptr;
   PFN_vkCmdPipelineBarrier cmd_pipeline_barrier = nullptr;
   PFN_vkCmdClearColorImage cmd_clear_color_image = nullptr;
   PFN_vkCmdCopyImageToBuffer cmd_copy_image_to_buffer = nullptr;
   PFN_vkInvalidateMappedMemoryRanges invalidate_mapped_memory_ranges = nullptr;

   VkCommandPool command_pool = VK_NULL_HANDLE;
   std::array<VkCommandBuffer, kFramesInFlight> command_buffers{};
   std::array<VkFence, kFramesInFlight> fences{};
   std::array<bool, kFramesInFlight> fence_pending{};
   std::array<VkSemaphore, kFramesInFlight> image_available{};
   std::vector<VkSemaphore> present_ready;
   std::vector<VkImage> swapchain_images;
   std::vector<bool> swapchain_initialized;
   unsigned present_slot = 0;
   HWND window = nullptr;
   VkBuffer staging_buffer = VK_NULL_HANDLE;
   VkDeviceMemory staging_memory = VK_NULL_HANDLE;
   void *mapped_staging = nullptr;
   VkDeviceSize staging_capacity = 0;
   bool staging_coherent = false;
   std::vector<uint8_t> converted_pixels;

   retro_hw_render_interface_vulkan interface{};
   retro_hw_render_callback *core_hw_callback = nullptr;
   retro_hw_render_context_negotiation_interface_vulkan *negotiation = nullptr;
   retro_vulkan_context core_context{};
   retro_vulkan_image current_image{};
   bool has_image = false;
   bool visible = false;
   unsigned sync_index = 0;
   unsigned long long frame_number = 0;
   VkFormat last_pixel_format = VK_FORMAT_UNDEFINED;
   std::string adapter_name;
   std::mutex queue_mutex;

   bool load_loader(char *error, size_t error_cap)
   {
      loader = LoadLibraryW(L"vulkan-1.dll");
      if (!loader)
      {
         set_error(error, error_cap, "Vulkan loader vulkan-1.dll no esta instalado.");
         return false;
      }
      gipa = reinterpret_cast<PFN_vkGetInstanceProcAddr>(GetProcAddress(loader, "vkGetInstanceProcAddr"));
      if (!gipa)
      {
         set_error(error, error_cap, "El loader de Vulkan no exporta vkGetInstanceProcAddr.");
         return false;
      }
      create_instance = reinterpret_cast<PFN_vkCreateInstance>(GetProcAddress(loader, "vkCreateInstance"));
      if (!create_instance)
         create_instance = load_instance_function<PFN_vkCreateInstance>(gipa, VK_NULL_HANDLE, "vkCreateInstance");
      if (!create_instance)
      {
         set_error(error, error_cap, "No se encontro vkCreateInstance en el loader.");
         return false;
      }
      return true;
   }

   bool create_instance_and_select_gpu(char *error, size_t error_cap)
   {
      VkApplicationInfo app{};
      app.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
      app.pApplicationName = "TM3 Online SYSTEM256";
      app.applicationVersion = VK_MAKE_VERSION(1, 0, 0);
      app.pEngineName = "TM3 Online";
      app.engineVersion = VK_MAKE_VERSION(1, 0, 0);
      app.apiVersion = VK_API_VERSION_1_0;

      VkInstanceCreateInfo info{};
      info.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
      info.pApplicationInfo = &app;
      const char *instance_extensions[] = { VK_KHR_SURFACE_EXTENSION_NAME, VK_KHR_WIN32_SURFACE_EXTENSION_NAME };
      if (window)
      {
         info.enabledExtensionCount = 2;
         info.ppEnabledExtensionNames = instance_extensions;
      }
      VkResult result = create_instance(&info, nullptr, &instance);
      if (result != VK_SUCCESS)
      {
         char message[128];
         std::snprintf(message, sizeof(message), "vkCreateInstance fallo (%d).", static_cast<int>(result));
         set_error(error, error_cap, message);
         return false;
      }

      destroy_instance = load_instance_function<PFN_vkDestroyInstance>(gipa, instance, "vkDestroyInstance");
      enumerate_physical_devices = load_instance_function<PFN_vkEnumeratePhysicalDevices>(gipa, instance, "vkEnumeratePhysicalDevices");
      get_physical_device_properties = load_instance_function<PFN_vkGetPhysicalDeviceProperties>(gipa, instance, "vkGetPhysicalDeviceProperties");
      get_queue_family_properties = load_instance_function<PFN_vkGetPhysicalDeviceQueueFamilyProperties>(gipa, instance, "vkGetPhysicalDeviceQueueFamilyProperties");
      get_memory_properties = load_instance_function<PFN_vkGetPhysicalDeviceMemoryProperties>(gipa, instance, "vkGetPhysicalDeviceMemoryProperties");
      gdpa = load_instance_function<PFN_vkGetDeviceProcAddr>(gipa, instance, "vkGetDeviceProcAddr");
      if (window)
      {
         create_win32_surface = load_instance_function<PFN_vkCreateWin32SurfaceKHR>(gipa, instance, "vkCreateWin32SurfaceKHR");
         destroy_surface = load_instance_function<PFN_vkDestroySurfaceKHR>(gipa, instance, "vkDestroySurfaceKHR");
         get_surface_support = load_instance_function<PFN_vkGetPhysicalDeviceSurfaceSupportKHR>(gipa, instance, "vkGetPhysicalDeviceSurfaceSupportKHR");
         get_surface_capabilities = load_instance_function<PFN_vkGetPhysicalDeviceSurfaceCapabilitiesKHR>(gipa, instance, "vkGetPhysicalDeviceSurfaceCapabilitiesKHR");
         get_surface_formats = load_instance_function<PFN_vkGetPhysicalDeviceSurfaceFormatsKHR>(gipa, instance, "vkGetPhysicalDeviceSurfaceFormatsKHR");
         get_surface_present_modes = load_instance_function<PFN_vkGetPhysicalDeviceSurfacePresentModesKHR>(gipa, instance, "vkGetPhysicalDeviceSurfacePresentModesKHR");
         if (!create_win32_surface || !destroy_surface || !get_surface_support ||
             !get_surface_capabilities || !get_surface_formats || !get_surface_present_modes)
         {
            set_error(error, error_cap, "El driver no expone las extensiones Vulkan de ventana Win32.");
            return false;
         }
         VkWin32SurfaceCreateInfoKHR surface_info{};
         surface_info.sType = VK_STRUCTURE_TYPE_WIN32_SURFACE_CREATE_INFO_KHR;
         surface_info.hinstance = GetModuleHandleW(nullptr);
         surface_info.hwnd = window;
         result = create_win32_surface(instance, &surface_info, nullptr, &surface);
         if (result != VK_SUCCESS)
         {
            char message[128];
            std::snprintf(message, sizeof(message), "vkCreateWin32SurfaceKHR fallo (%d).", static_cast<int>(result));
            set_error(error, error_cap, message);
            return false;
         }
      }
      if (!destroy_instance || !enumerate_physical_devices || !get_physical_device_properties ||
          !get_queue_family_properties || !get_memory_properties || !gdpa)
      {
         set_error(error, error_cap, "El driver no expone las funciones Vulkan requeridas.");
         return false;
      }

      uint32_t count = 0;
      result = enumerate_physical_devices(instance, &count, nullptr);
      if (result != VK_SUCCESS || count == 0)
      {
         set_error(error, error_cap, "Vulkan no encontro una GPU fisica disponible.");
         return false;
      }
      std::vector<VkPhysicalDevice> devices(count);
      result = enumerate_physical_devices(instance, &count, devices.data());
      if (result != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudieron enumerar las GPU Vulkan.");
         return false;
      }

      int best_score = -1;
      VkPhysicalDeviceProperties best_properties{};
      for (VkPhysicalDevice candidate : devices)
      {
         VkPhysicalDeviceProperties properties{};
         get_physical_device_properties(candidate, &properties);
         uint32_t family_count = 0;
         get_queue_family_properties(candidate, &family_count, nullptr);
         std::vector<VkQueueFamilyProperties> families(family_count);
         get_queue_family_properties(candidate, &family_count, families.data());
         bool usable = false;
         for (uint32_t family_index = 0; family_index < family_count; ++family_index)
         {
            const auto &family = families[family_index];
            if ((family.queueFlags & (VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT)) ==
                (VK_QUEUE_GRAPHICS_BIT | VK_QUEUE_COMPUTE_BIT) && family.queueCount)
            {
               VkBool32 present_supported = VK_TRUE;
               if (surface && get_surface_support(candidate, family_index, surface, &present_supported) != VK_SUCCESS)
                  present_supported = VK_FALSE;
               if (present_supported)
                  usable = true;
            }
         }
         if (!usable)
            continue;

         int score = properties.deviceType == VK_PHYSICAL_DEVICE_TYPE_DISCRETE_GPU ? 100 : 0;
         if (score > best_score)
         {
            best_score = score;
            gpu = candidate;
            best_properties = properties;
         }
      }
      if (gpu == VK_NULL_HANDLE)
      {
         set_error(error, error_cap, "No hay una GPU Vulkan con cola grafica y de computo.");
         return false;
      }
      adapter_name = best_properties.deviceName;
      return true;
   }

   template <typename T>
   bool load_device_function(T &out, const char *name, char *error, size_t error_cap)
   {
      out = reinterpret_cast<T>(gdpa(device, name));
      if (!out)
      {
         std::string message = "El driver no expone ";
         message += name;
         set_error(error, error_cap, message.c_str());
         return false;
      }
      return true;
   }

   bool load_device_functions(char *error, size_t error_cap)
   {
#define LOAD_DEVICE(member, symbol) if (!load_device_function(member, symbol, error, error_cap)) return false
      LOAD_DEVICE(destroy_device, "vkDestroyDevice");
      LOAD_DEVICE(create_command_pool, "vkCreateCommandPool");
      LOAD_DEVICE(destroy_command_pool, "vkDestroyCommandPool");
      LOAD_DEVICE(allocate_command_buffers, "vkAllocateCommandBuffers");
      LOAD_DEVICE(reset_command_buffer, "vkResetCommandBuffer");
      LOAD_DEVICE(begin_command_buffer, "vkBeginCommandBuffer");
      LOAD_DEVICE(end_command_buffer, "vkEndCommandBuffer");
      LOAD_DEVICE(create_fence, "vkCreateFence");
      LOAD_DEVICE(destroy_fence, "vkDestroyFence");
      LOAD_DEVICE(wait_for_fences, "vkWaitForFences");
      LOAD_DEVICE(reset_fences, "vkResetFences");
      LOAD_DEVICE(queue_submit, "vkQueueSubmit");
      LOAD_DEVICE(queue_wait_idle, "vkQueueWaitIdle");
      LOAD_DEVICE(device_wait_idle, "vkDeviceWaitIdle");
      LOAD_DEVICE(create_buffer, "vkCreateBuffer");
      LOAD_DEVICE(destroy_buffer, "vkDestroyBuffer");
      LOAD_DEVICE(get_buffer_memory_requirements, "vkGetBufferMemoryRequirements");
      LOAD_DEVICE(allocate_memory, "vkAllocateMemory");
      LOAD_DEVICE(free_memory, "vkFreeMemory");
      LOAD_DEVICE(bind_buffer_memory, "vkBindBufferMemory");
      LOAD_DEVICE(map_memory, "vkMapMemory");
      LOAD_DEVICE(unmap_memory, "vkUnmapMemory");
      LOAD_DEVICE(cmd_pipeline_barrier, "vkCmdPipelineBarrier");
      LOAD_DEVICE(cmd_clear_color_image, "vkCmdClearColorImage");
      LOAD_DEVICE(cmd_copy_image_to_buffer, "vkCmdCopyImageToBuffer");
      LOAD_DEVICE(cmd_blit_image, "vkCmdBlitImage");
      LOAD_DEVICE(invalidate_mapped_memory_ranges, "vkInvalidateMappedMemoryRanges");
      LOAD_DEVICE(create_semaphore, "vkCreateSemaphore");
      LOAD_DEVICE(destroy_semaphore, "vkDestroySemaphore");
#undef LOAD_DEVICE
      return true;
   }

   bool load_swapchain_functions(char *error, size_t error_cap)
   {
#define LOAD_SWAPCHAIN(member, symbol) if (!load_device_function(member, symbol, error, error_cap)) return false
      LOAD_SWAPCHAIN(create_swapchain, "vkCreateSwapchainKHR");
      LOAD_SWAPCHAIN(destroy_swapchain, "vkDestroySwapchainKHR");
      LOAD_SWAPCHAIN(get_swapchain_images, "vkGetSwapchainImagesKHR");
      LOAD_SWAPCHAIN(acquire_next_image, "vkAcquireNextImageKHR");
      LOAD_SWAPCHAIN(queue_present, "vkQueuePresentKHR");
#undef LOAD_SWAPCHAIN
      return true;
   }

   bool create_readback_resources(char *error, size_t error_cap)
   {
      VkCommandPoolCreateInfo pool_info{};
      pool_info.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
      pool_info.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
      pool_info.queueFamilyIndex = queue_family;
      VkResult result = create_command_pool(device, &pool_info, nullptr, &command_pool);
      if (result != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudo crear el command pool Vulkan.");
         return false;
      }

      VkCommandBufferAllocateInfo command_info{};
      command_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
      command_info.commandPool = command_pool;
      command_info.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
      command_info.commandBufferCount = kFramesInFlight;
      result = allocate_command_buffers(device, &command_info, command_buffers.data());
      if (result != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudieron crear command buffers Vulkan.");
         return false;
      }

      for (unsigned i = 0; i < kFramesInFlight; ++i)
      {
         VkFenceCreateInfo fence_info{};
         fence_info.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
         fence_info.flags = VK_FENCE_CREATE_SIGNALED_BIT;
         result = create_fence(device, &fence_info, nullptr, &fences[i]);
         if (result != VK_SUCCESS)
         {
            set_error(error, error_cap, "No se pudo crear un fence Vulkan.");
            return false;
         }
         if (surface)
         {
            VkSemaphoreCreateInfo semaphore_info{};
            semaphore_info.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;
            result = create_semaphore(device, &semaphore_info, nullptr, &image_available[i]);
            if (result != VK_SUCCESS)
            {
               set_error(error, error_cap, "No se pudo crear un semaforo de imagen Vulkan.");
               return false;
            }
         }
      }
      return true;
   }

   bool update_swapchain(char *error, size_t error_cap)
   {
      if (!surface)
         return true;
      VkSurfaceCapabilitiesKHR caps{};
      VkResult result = get_surface_capabilities(gpu, surface, &caps);
      if (result != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudieron leer las capacidades de la ventana Vulkan.");
         return false;
      }
      if (!(caps.supportedUsageFlags & VK_IMAGE_USAGE_TRANSFER_DST_BIT))
      {
         set_error(error, error_cap, "La ventana Vulkan no permite presentar por transferencia de imagen.");
         return false;
      }

      VkExtent2D extent = caps.currentExtent;
      if (extent.width == UINT32_MAX || extent.height == UINT32_MAX)
      {
         RECT client{};
         if (!GetClientRect(window, &client))
         {
            set_error(error, error_cap, "No se pudo consultar el tamano de la ventana TM3.");
            return false;
         }
         const uint32_t width = static_cast<uint32_t>(std::max<LONG>(0, client.right - client.left));
         const uint32_t height = static_cast<uint32_t>(std::max<LONG>(0, client.bottom - client.top));
         if (!width || !height)
            return true; // Minimized window; keep the previous swapchain.
         extent.width = std::clamp(width, caps.minImageExtent.width, caps.maxImageExtent.width);
         extent.height = std::clamp(height, caps.minImageExtent.height, caps.maxImageExtent.height);
      }
      if (!extent.width || !extent.height)
         return true;
      if (swapchain && swapchain_extent.width == extent.width && swapchain_extent.height == extent.height)
         return true;

      uint32_t format_count = 0;
      result = get_surface_formats(gpu, surface, &format_count, nullptr);
      if (result != VK_SUCCESS || !format_count)
      {
         set_error(error, error_cap, "La ventana no anuncio formatos compatibles con Vulkan.");
         return false;
      }
      std::vector<VkSurfaceFormatKHR> formats(format_count);
      result = get_surface_formats(gpu, surface, &format_count, formats.data());
      if (result != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudieron enumerar los formatos de presentacion Vulkan.");
         return false;
      }
      VkSurfaceFormatKHR surface_format = formats.front();
      for (const auto &candidate : formats)
         if (candidate.format == VK_FORMAT_B8G8R8A8_UNORM && candidate.colorSpace == VK_COLOR_SPACE_SRGB_NONLINEAR_KHR)
         {
            surface_format = candidate;
            break;
         }

      uint32_t mode_count = 0;
      result = get_surface_present_modes(gpu, surface, &mode_count, nullptr);
      if (result != VK_SUCCESS || !mode_count)
      {
         set_error(error, error_cap, "La ventana no anuncio modos de presentacion Vulkan.");
         return false;
      }
      std::vector<VkPresentModeKHR> modes(mode_count);
      result = get_surface_present_modes(gpu, surface, &mode_count, modes.data());
      if (result != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudieron enumerar los modos Vulkan.");
         return false;
      }
      VkPresentModeKHR present_mode = VK_PRESENT_MODE_FIFO_KHR;
      if (std::find(modes.begin(), modes.end(), VK_PRESENT_MODE_MAILBOX_KHR) != modes.end())
         present_mode = VK_PRESENT_MODE_MAILBOX_KHR;

      uint32_t image_count = caps.minImageCount + 1;
      if (caps.maxImageCount && image_count > caps.maxImageCount)
         image_count = caps.maxImageCount;
      VkCompositeAlphaFlagBitsKHR alpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
      if (!(caps.supportedCompositeAlpha & alpha))
      {
         const VkCompositeAlphaFlagBitsKHR choices[] = { VK_COMPOSITE_ALPHA_PRE_MULTIPLIED_BIT_KHR,
            VK_COMPOSITE_ALPHA_POST_MULTIPLIED_BIT_KHR, VK_COMPOSITE_ALPHA_INHERIT_BIT_KHR };
         for (VkCompositeAlphaFlagBitsKHR choice : choices)
            if (caps.supportedCompositeAlpha & choice) { alpha = choice; break; }
      }
      VkSwapchainCreateInfoKHR info{};
      info.sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR;
      info.surface = surface;
      info.minImageCount = image_count;
      info.imageFormat = surface_format.format;
      info.imageColorSpace = surface_format.colorSpace;
      info.imageExtent = extent;
      info.imageArrayLayers = 1;
      info.imageUsage = VK_IMAGE_USAGE_TRANSFER_DST_BIT;
      info.imageSharingMode = VK_SHARING_MODE_EXCLUSIVE;
      info.preTransform = caps.currentTransform;
      info.compositeAlpha = alpha;
      info.presentMode = present_mode;
      info.clipped = VK_TRUE;
      info.oldSwapchain = swapchain;
      VkSwapchainKHR next_swapchain = VK_NULL_HANDLE;
      result = create_swapchain(device, &info, nullptr, &next_swapchain);
      if (result != VK_SUCCESS)
      {
         char message[128];
         std::snprintf(message, sizeof(message), "vkCreateSwapchainKHR fallo (%d).", static_cast<int>(result));
         set_error(error, error_cap, message);
         return false;
      }
      device_wait_idle(device);
      if (swapchain)
         destroy_swapchain(device, swapchain, nullptr);
      for (VkSemaphore semaphore : present_ready)
         if (semaphore) destroy_semaphore(device, semaphore, nullptr);
      present_ready.clear();
      swapchain = next_swapchain;
      swapchain_format = surface_format.format;
      swapchain_extent = extent;

      uint32_t actual_count = 0;
      result = get_swapchain_images(device, swapchain, &actual_count, nullptr);
      if (result != VK_SUCCESS || !actual_count)
      {
         set_error(error, error_cap, "No se pudieron obtener las imagenes del swapchain Vulkan.");
         return false;
      }
      swapchain_images.resize(actual_count);
      result = get_swapchain_images(device, swapchain, &actual_count, swapchain_images.data());
      if (result != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudieron obtener las imagenes del swapchain Vulkan.");
         return false;
      }
      present_ready.resize(actual_count, VK_NULL_HANDLE);
      swapchain_initialized.assign(actual_count, false);
      VkSemaphoreCreateInfo semaphore_info{};
      semaphore_info.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;
      for (auto &semaphore : present_ready)
      {
         result = create_semaphore(device, &semaphore_info, nullptr, &semaphore);
         if (result != VK_SUCCESS)
         {
            set_error(error, error_cap, "No se pudo crear un semaforo de presentacion Vulkan.");
            return false;
         }
      }
      return true;
   }

   void release_staging()
   {
      if (mapped_staging && unmap_memory)
         unmap_memory(device, staging_memory);
      mapped_staging = nullptr;
      if (staging_buffer && destroy_buffer)
         destroy_buffer(device, staging_buffer, nullptr);
      staging_buffer = VK_NULL_HANDLE;
      if (staging_memory && free_memory)
         free_memory(device, staging_memory, nullptr);
      staging_memory = VK_NULL_HANDLE;
      staging_capacity = 0;
   }

   bool ensure_staging_buffer(VkDeviceSize required, char *error, size_t error_cap)
   {
      if (required <= staging_capacity && staging_buffer && mapped_staging)
         return true;
      release_staging();

      VkBufferCreateInfo buffer_info{};
      buffer_info.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
      buffer_info.size = required;
      buffer_info.usage = VK_BUFFER_USAGE_TRANSFER_DST_BIT;
      buffer_info.sharingMode = VK_SHARING_MODE_EXCLUSIVE;
      VkResult result = create_buffer(device, &buffer_info, nullptr, &staging_buffer);
      if (result != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudo crear el buffer de lectura Vulkan.");
         return false;
      }

      VkMemoryRequirements requirements{};
      get_buffer_memory_requirements(device, staging_buffer, &requirements);
      VkPhysicalDeviceMemoryProperties memory_properties{};
      get_memory_properties(gpu, &memory_properties);
      int coherent_type = -1;
      int visible_type = -1;
      for (uint32_t i = 0; i < memory_properties.memoryTypeCount; ++i)
      {
         if (!(requirements.memoryTypeBits & (1u << i)))
            continue;
         const VkMemoryPropertyFlags flags = memory_properties.memoryTypes[i].propertyFlags;
         if (flags & VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT)
         {
            if (visible_type < 0)
               visible_type = static_cast<int>(i);
            if (flags & VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)
            {
               coherent_type = static_cast<int>(i);
               break;
            }
         }
      }
      const int memory_type = coherent_type >= 0 ? coherent_type : visible_type;
      if (memory_type < 0)
      {
         set_error(error, error_cap, "La GPU no ofrece memoria Vulkan visible desde CPU.");
         return false;
      }

      VkMemoryAllocateInfo memory_info{};
      memory_info.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
      memory_info.allocationSize = requirements.size;
      memory_info.memoryTypeIndex = static_cast<uint32_t>(memory_type);
      result = allocate_memory(device, &memory_info, nullptr, &staging_memory);
      if (result != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudo asignar memoria para el buffer Vulkan.");
         return false;
      }
      result = bind_buffer_memory(device, staging_buffer, staging_memory, 0);
      if (result != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudo enlazar memoria al buffer Vulkan.");
         return false;
      }
      result = map_memory(device, staging_memory, 0, requirements.size, 0, &mapped_staging);
      if (result != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudo mapear el buffer de lectura Vulkan.");
         return false;
      }
      staging_capacity = requirements.size;
      staging_coherent = coherent_type >= 0;
      return true;
   }

   static void RETRO_CALLCONV set_image(void *opaque, const retro_vulkan_image *image,
         uint32_t, const VkSemaphore *, uint32_t)
   {
      VulkanCore *self = static_cast<VulkanCore *>(opaque);
      if (image)
      {
         self->current_image = *image;
         self->has_image = image->create_info.image != VK_NULL_HANDLE;
         self->last_pixel_format = image->create_info.format;
      }
   }

   static uint32_t RETRO_CALLCONV get_sync_index(void *opaque)
   {
      return static_cast<VulkanCore *>(opaque)->sync_index;
   }

   static uint32_t RETRO_CALLCONV get_sync_index_mask(void *)
   {
      return (1u << kFramesInFlight) - 1u;
   }

   static void RETRO_CALLCONV wait_sync_index(void *opaque)
   {
      VulkanCore *self = static_cast<VulkanCore *>(opaque);
      const unsigned slot = self->sync_index % kFramesInFlight;
      if (!self->fence_pending[slot])
         return;
      std::lock_guard<std::mutex> lock(self->queue_mutex);
      if (self->wait_for_fences(self->device, 1, &self->fences[slot], VK_TRUE, UINT64_MAX) == VK_SUCCESS)
         self->fence_pending[slot] = false;
   }

   static void RETRO_CALLCONV lock_queue(void *opaque)
   {
      static_cast<VulkanCore *>(opaque)->queue_mutex.lock();
   }

   static void RETRO_CALLCONV unlock_queue(void *opaque)
   {
      static_cast<VulkanCore *>(opaque)->queue_mutex.unlock();
   }

   bool submit_marker(unsigned slot, VkCommandBuffer command, char *error, size_t error_cap)
   {
      VkResult result = reset_fences(device, 1, &fences[slot]);
      if (result != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudo reiniciar un fence Vulkan.");
         return false;
      }
      VkSubmitInfo submit{};
      submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
      if (command != VK_NULL_HANDLE)
      {
         submit.commandBufferCount = 1;
         submit.pCommandBuffers = &command;
      }
      result = queue_submit(queue, 1, &submit, fences[slot]);
      if (result != VK_SUCCESS)
      {
         set_error(error, error_cap, "vkQueueSubmit fallo al cerrar el cuadro.");
         return false;
      }
      fence_pending[slot] = true;
      return true;
   }

   bool readback(uint32_t width, uint32_t height, const void **pixels, size_t *pitch,
         unsigned *pixel_format, char *error, size_t error_cap)
   {
      if (!visible || !has_image || !width || !height)
      {
         set_error(error, error_cap, "No hay un cuadro Vulkan visible para leer.");
         return false;
      }
      const bool rgba8 = last_pixel_format == VK_FORMAT_R8G8B8A8_UNORM ||
          last_pixel_format == VK_FORMAT_B8G8R8A8_UNORM ||
          last_pixel_format == VK_FORMAT_R8G8B8A8_SRGB ||
          last_pixel_format == VK_FORMAT_B8G8R8A8_SRGB;
      const bool rgb16 = last_pixel_format == VK_FORMAT_R5G6B5_UNORM_PACK16 ||
          last_pixel_format == VK_FORMAT_B5G6R5_UNORM_PACK16 ||
          last_pixel_format == VK_FORMAT_R5G5B5A1_UNORM_PACK16 ||
          last_pixel_format == VK_FORMAT_B5G5R5A1_UNORM_PACK16 ||
          last_pixel_format == VK_FORMAT_A1R5G5B5_UNORM_PACK16;
      if (!rgba8 && !rgb16)
      {
         char message[128];
         std::snprintf(message, sizeof(message), "Formato Vulkan de salida no compatible (%d).", static_cast<int>(last_pixel_format));
         set_error(error, error_cap, message);
         return false;
      }

      const unsigned source_bytes_per_pixel = rgba8 ? 4u : 2u;
      const VkDeviceSize bytes = static_cast<VkDeviceSize>(width) * height * source_bytes_per_pixel;
      if (!ensure_staging_buffer(bytes, error, error_cap))
         return false;

      const unsigned slot = sync_index % kFramesInFlight;
      VkCommandBuffer command = command_buffers[slot];
      if (reset_command_buffer(command, 0) != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudo reiniciar un command buffer Vulkan.");
         return false;
      }
      VkCommandBufferBeginInfo begin{};
      begin.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
      begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
      if (begin_command_buffer(command, &begin) != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudo iniciar el command buffer Vulkan.");
         return false;
      }

      VkImageMemoryBarrier to_transfer{};
      to_transfer.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
      to_transfer.srcAccessMask = VK_ACCESS_SHADER_READ_BIT;
      to_transfer.dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
      to_transfer.oldLayout = current_image.image_layout;
      to_transfer.newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
      to_transfer.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
      to_transfer.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
      to_transfer.image = current_image.create_info.image;
      to_transfer.subresourceRange = current_image.create_info.subresourceRange;
      cmd_pipeline_barrier(command, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
            0, 0, nullptr, 0, nullptr, 1, &to_transfer);

      VkBufferImageCopy copy{};
      copy.imageSubresource.aspectMask = current_image.create_info.subresourceRange.aspectMask;
      copy.imageSubresource.mipLevel = current_image.create_info.subresourceRange.baseMipLevel;
      copy.imageSubresource.baseArrayLayer = current_image.create_info.subresourceRange.baseArrayLayer;
      copy.imageSubresource.layerCount = current_image.create_info.subresourceRange.layerCount;
      copy.imageOffset = { 0, 0, 0 };
      copy.imageExtent = { width, height, 1 };
      cmd_copy_image_to_buffer(command, current_image.create_info.image,
            VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL, staging_buffer, 1, &copy);

      VkImageMemoryBarrier to_shader{};
      to_shader.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
      to_shader.srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
      to_shader.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
      to_shader.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
      to_shader.newLayout = current_image.image_layout;
      to_shader.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
      to_shader.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
      to_shader.image = current_image.create_info.image;
      to_shader.subresourceRange = current_image.create_info.subresourceRange;
      cmd_pipeline_barrier(command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
            0, 0, nullptr, 0, nullptr, 1, &to_shader);
      if (end_command_buffer(command) != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudo cerrar el command buffer Vulkan.");
         return false;
      }

      {
         std::lock_guard<std::mutex> lock(queue_mutex);
         if (!submit_marker(slot, command, error, error_cap))
            return false;
         VkResult result = wait_for_fences(device, 1, &fences[slot], VK_TRUE, UINT64_MAX);
         if (result != VK_SUCCESS)
         {
            set_error(error, error_cap, "La lectura Vulkan no termino correctamente.");
            return false;
         }
         fence_pending[slot] = false;
      }

      if (!staging_coherent)
      {
         VkMappedMemoryRange range{};
         range.sType = VK_STRUCTURE_TYPE_MAPPED_MEMORY_RANGE;
         range.memory = staging_memory;
         range.offset = 0;
         range.size = VK_WHOLE_SIZE;
         if (invalidate_mapped_memory_ranges(device, 1, &range) != VK_SUCCESS)
         {
            set_error(error, error_cap, "No se pudo invalidar la cache de lectura Vulkan.");
            return false;
         }
      }

      *pitch = static_cast<size_t>(width) * 4u;
      if (rgba8)
      {
         *pixels = mapped_staging;
         *pixel_format = (last_pixel_format == VK_FORMAT_B8G8R8A8_UNORM ||
                          last_pixel_format == VK_FORMAT_B8G8R8A8_SRGB) ? 4u : 3u;
      }
      else
      {
         const uint16_t *source = static_cast<const uint16_t *>(mapped_staging);
         converted_pixels.resize(static_cast<size_t>(width) * height * 4u);
         auto expand5 = [](unsigned value) { return static_cast<uint8_t>((value * 255u + 15u) / 31u); };
         auto expand6 = [](unsigned value) { return static_cast<uint8_t>((value * 255u + 31u) / 63u); };
         for (size_t i = 0, count = static_cast<size_t>(width) * height; i < count; ++i)
         {
            const uint16_t value = source[i];
            unsigned r = 0, g = 0, b = 0;
            if (last_pixel_format == VK_FORMAT_R5G6B5_UNORM_PACK16)
            {
               r = expand5((value >> 11) & 31u); g = expand6((value >> 5) & 63u); b = expand5(value & 31u);
            }
            else if (last_pixel_format == VK_FORMAT_B5G6R5_UNORM_PACK16)
            {
               b = expand5((value >> 11) & 31u); g = expand6((value >> 5) & 63u); r = expand5(value & 31u);
            }
            else if (last_pixel_format == VK_FORMAT_R5G5B5A1_UNORM_PACK16)
            {
               r = expand5((value >> 11) & 31u); g = expand5((value >> 6) & 31u); b = expand5((value >> 1) & 31u);
            }
            else if (last_pixel_format == VK_FORMAT_B5G5R5A1_UNORM_PACK16)
            {
               b = expand5((value >> 11) & 31u); g = expand5((value >> 6) & 31u); r = expand5((value >> 1) & 31u);
            }
            else /* VK_FORMAT_A1R5G5B5_UNORM_PACK16 */
            {
               r = expand5((value >> 10) & 31u); g = expand5((value >> 5) & 31u); b = expand5(value & 31u);
            }
            converted_pixels[i * 4u + 0] = static_cast<uint8_t>(r);
            converted_pixels[i * 4u + 1] = static_cast<uint8_t>(g);
            converted_pixels[i * 4u + 2] = static_cast<uint8_t>(b);
            converted_pixels[i * 4u + 3] = 255;
         }
         *pixels = converted_pixels.data();
         *pixel_format = 3u;
      }
      return true;
   }

   bool present(uint32_t width, uint32_t height, bool smooth, bool preserve_aspect,
         char *error, size_t error_cap)
   {
      if (!visible || !surface || !has_image || !width || !height)
      {
         set_error(error, error_cap, "No hay una imagen Vulkan valida para presentar.");
         return false;
      }
      if (!update_swapchain(error, error_cap))
         return false;
      if (!swapchain)
      {
         const unsigned slot = sync_index % kFramesInFlight;
         std::lock_guard<std::mutex> lock(queue_mutex);
         return submit_marker(slot, VK_NULL_HANDLE, error, error_cap);
      }

      int32_t dst_x0 = 0;
      int32_t dst_y0 = 0;
      int32_t dst_x1 = static_cast<int32_t>(swapchain_extent.width);
      int32_t dst_y1 = static_cast<int32_t>(swapchain_extent.height);
      if (preserve_aspect)
      {
         // TM3 always presents in a 4:3 viewport, even when the game reports
         // a 320x224/visible-area frame or the user maximizes a wide window.
         const uint64_t window_cross = static_cast<uint64_t>(swapchain_extent.width) * 3u;
         const uint64_t game_cross = static_cast<uint64_t>(swapchain_extent.height) * 4u;
         if (window_cross > game_cross)
         {
            const uint32_t content_width = static_cast<uint32_t>(
                  static_cast<uint64_t>(swapchain_extent.height) * 4u / 3u);
            dst_x0 = static_cast<int32_t>((swapchain_extent.width - content_width) / 2u);
            dst_x1 = dst_x0 + static_cast<int32_t>(content_width);
         }
         else if (window_cross < game_cross)
         {
            const uint32_t content_height = static_cast<uint32_t>(
                  static_cast<uint64_t>(swapchain_extent.width) * 3u / 4u);
            dst_y0 = static_cast<int32_t>((swapchain_extent.height - content_height) / 2u);
            dst_y1 = dst_y0 + static_cast<int32_t>(content_height);
         }
      }

      const unsigned slot = sync_index % kFramesInFlight;
      uint32_t image_index = 0;
      VkResult result = acquire_next_image(device, swapchain, UINT64_MAX,
            image_available[slot], VK_NULL_HANDLE, &image_index);
      if (result == VK_ERROR_OUT_OF_DATE_KHR)
      {
         swapchain_extent = {};
         if (!update_swapchain(error, error_cap))
            return false;
         result = acquire_next_image(device, swapchain, UINT64_MAX,
               image_available[slot], VK_NULL_HANDLE, &image_index);
      }
      if (result != VK_SUCCESS && result != VK_SUBOPTIMAL_KHR)
      {
         char message[128];
         std::snprintf(message, sizeof(message), "vkAcquireNextImageKHR fallo (%d).", static_cast<int>(result));
         set_error(error, error_cap, message);
         return false;
      }

      VkCommandBuffer command = command_buffers[slot];
      if (reset_command_buffer(command, 0) != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudo reiniciar el command buffer de presentacion.");
         return false;
      }
      VkCommandBufferBeginInfo begin{};
      begin.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
      begin.flags = VK_COMMAND_BUFFER_USAGE_ONE_TIME_SUBMIT_BIT;
      if (begin_command_buffer(command, &begin) != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudo iniciar el command buffer de presentacion.");
         return false;
      }

      VkImageMemoryBarrier source_to_transfer{};
      source_to_transfer.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
      source_to_transfer.srcAccessMask = VK_ACCESS_SHADER_READ_BIT;
      source_to_transfer.dstAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
      source_to_transfer.oldLayout = current_image.image_layout;
      source_to_transfer.newLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
      source_to_transfer.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
      source_to_transfer.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
      source_to_transfer.image = current_image.create_info.image;
      source_to_transfer.subresourceRange = current_image.create_info.subresourceRange;
      cmd_pipeline_barrier(command, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
            0, 0, nullptr, 0, nullptr, 1, &source_to_transfer);

      VkImageMemoryBarrier destination_to_transfer{};
      destination_to_transfer.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
      destination_to_transfer.srcAccessMask = 0;
      destination_to_transfer.dstAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
      destination_to_transfer.oldLayout = swapchain_initialized[image_index] ? VK_IMAGE_LAYOUT_PRESENT_SRC_KHR : VK_IMAGE_LAYOUT_UNDEFINED;
      destination_to_transfer.newLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
      destination_to_transfer.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
      destination_to_transfer.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
      destination_to_transfer.image = swapchain_images[image_index];
      destination_to_transfer.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
      destination_to_transfer.subresourceRange.baseMipLevel = 0;
      destination_to_transfer.subresourceRange.levelCount = 1;
      destination_to_transfer.subresourceRange.baseArrayLayer = 0;
      destination_to_transfer.subresourceRange.layerCount = 1;
      cmd_pipeline_barrier(command, VK_PIPELINE_STAGE_TOP_OF_PIPE_BIT, VK_PIPELINE_STAGE_TRANSFER_BIT,
            0, 0, nullptr, 0, nullptr, 1, &destination_to_transfer);

      VkClearColorValue black{};
      black.float32[3] = 1.0f;
      VkImageSubresourceRange full_image{};
      full_image.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
      full_image.levelCount = 1;
      full_image.layerCount = 1;
      cmd_clear_color_image(command, swapchain_images[image_index],
            VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, &black, 1, &full_image);

      VkImageBlit blit{};
      blit.srcSubresource.aspectMask = current_image.create_info.subresourceRange.aspectMask;
      blit.srcSubresource.mipLevel = current_image.create_info.subresourceRange.baseMipLevel;
      blit.srcSubresource.baseArrayLayer = current_image.create_info.subresourceRange.baseArrayLayer;
      blit.srcSubresource.layerCount = 1;
      blit.srcOffsets[0] = { 0, 0, 0 };
      blit.srcOffsets[1] = { static_cast<int32_t>(width), static_cast<int32_t>(height), 1 };
      blit.dstSubresource.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
      blit.dstSubresource.mipLevel = 0;
      blit.dstSubresource.baseArrayLayer = 0;
      blit.dstSubresource.layerCount = 1;
      blit.dstOffsets[0] = { dst_x0, dst_y0, 0 };
      blit.dstOffsets[1] = { dst_x1, dst_y1, 1 };
      cmd_blit_image(command, current_image.create_info.image, VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL,
            swapchain_images[image_index], VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL, 1, &blit,
            smooth ? VK_FILTER_LINEAR : VK_FILTER_NEAREST);

      VkImageMemoryBarrier source_back{};
      source_back.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
      source_back.srcAccessMask = VK_ACCESS_TRANSFER_READ_BIT;
      source_back.dstAccessMask = VK_ACCESS_SHADER_READ_BIT;
      source_back.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_SRC_OPTIMAL;
      source_back.newLayout = current_image.image_layout;
      source_back.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
      source_back.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
      source_back.image = current_image.create_info.image;
      source_back.subresourceRange = current_image.create_info.subresourceRange;
      cmd_pipeline_barrier(command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,
            0, 0, nullptr, 0, nullptr, 1, &source_back);

      VkImageMemoryBarrier destination_to_present{};
      destination_to_present.sType = VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER;
      destination_to_present.srcAccessMask = VK_ACCESS_TRANSFER_WRITE_BIT;
      destination_to_present.dstAccessMask = 0;
      destination_to_present.oldLayout = VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;
      destination_to_present.newLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;
      destination_to_present.srcQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
      destination_to_present.dstQueueFamilyIndex = VK_QUEUE_FAMILY_IGNORED;
      destination_to_present.image = swapchain_images[image_index];
      destination_to_present.subresourceRange = destination_to_transfer.subresourceRange;
      cmd_pipeline_barrier(command, VK_PIPELINE_STAGE_TRANSFER_BIT, VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,
            0, 0, nullptr, 0, nullptr, 1, &destination_to_present);
      if (end_command_buffer(command) != VK_SUCCESS)
      {
         set_error(error, error_cap, "No se pudo cerrar el command buffer de presentacion.");
         return false;
      }

      VkPipelineStageFlags wait_stage = VK_PIPELINE_STAGE_TRANSFER_BIT;
      VkSubmitInfo submit{};
      submit.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
      submit.waitSemaphoreCount = 1;
      submit.pWaitSemaphores = &image_available[slot];
      submit.pWaitDstStageMask = &wait_stage;
      submit.commandBufferCount = 1;
      submit.pCommandBuffers = &command;
      submit.signalSemaphoreCount = 1;
      submit.pSignalSemaphores = &present_ready[image_index];
      VkPresentInfoKHR present_info{};
      present_info.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR;
      present_info.waitSemaphoreCount = 1;
      present_info.pWaitSemaphores = &present_ready[image_index];
      present_info.swapchainCount = 1;
      present_info.pSwapchains = &swapchain;
      present_info.pImageIndices = &image_index;
      {
         std::lock_guard<std::mutex> lock(queue_mutex);
         result = reset_fences(device, 1, &fences[slot]);
         if (result != VK_SUCCESS)
         {
            set_error(error, error_cap, "No se pudo reiniciar el fence de presentacion.");
            return false;
         }
         result = queue_submit(queue, 1, &submit, fences[slot]);
         if (result != VK_SUCCESS)
         {
            set_error(error, error_cap, "vkQueueSubmit fallo al presentar el cuadro.");
            return false;
         }
         fence_pending[slot] = true;
         swapchain_initialized[image_index] = true;
         result = queue_present(queue, &present_info);
      }
      if (result == VK_ERROR_OUT_OF_DATE_KHR || result == VK_SUBOPTIMAL_KHR)
         swapchain_extent = {};
      else if (result != VK_SUCCESS)
      {
         char message[128];
         std::snprintf(message, sizeof(message), "vkQueuePresentKHR fallo (%d).", static_cast<int>(result));
         set_error(error, error_cap, message);
         return false;
      }
      return true;
   }

   void destroy()
   {
      if (device && device_wait_idle)
      {
         std::lock_guard<std::mutex> lock(queue_mutex);
         device_wait_idle(device);
      }
      release_staging();
      if (device)
      {
         if (swapchain && destroy_swapchain)
            destroy_swapchain(device, swapchain, nullptr);
         swapchain = VK_NULL_HANDLE;
         for (VkSemaphore semaphore : present_ready)
            if (semaphore && destroy_semaphore)
               destroy_semaphore(device, semaphore, nullptr);
         present_ready.clear();
         for (VkSemaphore semaphore : image_available)
            if (semaphore && destroy_semaphore)
               destroy_semaphore(device, semaphore, nullptr);
         for (VkFence fence : fences)
            if (fence && destroy_fence)
               destroy_fence(device, fence, nullptr);
         if (command_pool && destroy_command_pool)
            destroy_command_pool(device, command_pool, nullptr);
         if (destroy_device)
            destroy_device(device, nullptr);
      }
      device = VK_NULL_HANDLE;
      if (surface && destroy_surface && instance)
         destroy_surface(instance, surface, nullptr);
      surface = VK_NULL_HANDLE;
      if (instance && destroy_instance)
         destroy_instance(instance, nullptr);
      instance = VK_NULL_HANDLE;
      if (loader)
         FreeLibrary(loader);
      loader = nullptr;
   }
};

} // namespace

extern "C" {

__declspec(dllexport) void *tm3vk_create_core(void *window_handle, char *error, size_t error_cap)
{
   VulkanCore *core = new (std::nothrow) VulkanCore();
   if (!core)
   {
      set_error(error, error_cap, "Sin memoria para inicializar Vulkan.");
      return nullptr;
   }
   core->window = static_cast<HWND>(window_handle);
   if (!core->load_loader(error, error_cap) || !core->create_instance_and_select_gpu(error, error_cap))
   {
      core->destroy();
      delete core;
      return nullptr;
   }
   return core;
}

__declspec(dllexport) int tm3vk_probe(char *adapter, size_t adapter_cap, char *error, size_t error_cap)
{
   VulkanCore *core = static_cast<VulkanCore *>(tm3vk_create_core(nullptr, error, error_cap));
   if (!core)
      return 0;
   if (adapter && adapter_cap)
   {
      std::snprintf(adapter, adapter_cap, "%s", core->adapter_name.c_str());
      adapter[adapter_cap - 1] = '\0';
   }
   core->destroy();
   delete core;
   return 1;
}

__declspec(dllexport) int tm3vk_attach_core(void *handle, void *negotiation_ptr,
      void *hw_callback_ptr, int visible, char *error, size_t error_cap)
{
   VulkanCore *core = static_cast<VulkanCore *>(handle);
   if (!core || !negotiation_ptr || !hw_callback_ptr)
   {
      set_error(error, error_cap, "El core Beetle no registro las interfaces Vulkan necesarias.");
      return 0;
   }
   core->negotiation = static_cast<retro_hw_render_context_negotiation_interface_vulkan *>(negotiation_ptr);
   core->core_hw_callback = static_cast<retro_hw_render_callback *>(hw_callback_ptr);
   core->visible = visible != 0;
   if (core->negotiation->interface_type != RETRO_HW_RENDER_CONTEXT_NEGOTIATION_INTERFACE_VULKAN ||
       !core->negotiation->create_device ||
       core->core_hw_callback->context_type != RETRO_HW_CONTEXT_VULKAN ||
       !core->core_hw_callback->context_reset)
   {
      set_error(error, error_cap, "La version de la interfaz Vulkan de Beetle no es compatible.");
      return 0;
   }

   const VkPhysicalDeviceFeatures no_required_features{};
   const char *swapchain_extension = VK_KHR_SWAPCHAIN_EXTENSION_NAME;
   if (!core->negotiation->create_device(&core->core_context, core->instance, core->gpu,
         core->surface, core->gipa, core->surface ? &swapchain_extension : nullptr,
         core->surface ? 1u : 0u, nullptr, 0, &no_required_features))
   {
      set_error(error, error_cap, "Beetle no pudo crear su dispositivo Vulkan en la GPU seleccionada.");
      return 0;
   }
   core->device = core->core_context.device;
   core->queue = core->core_context.queue;
   core->queue_family = core->core_context.queue_family_index;
   if (!core->device || !core->queue || !core->load_device_functions(error, error_cap) ||
       !core->create_readback_resources(error, error_cap) ||
       (core->surface && (!core->load_swapchain_functions(error, error_cap) ||
                          !core->update_swapchain(error, error_cap))))
      return 0;

   core->interface.interface_type = RETRO_HW_RENDER_INTERFACE_VULKAN;
   core->interface.interface_version = RETRO_HW_RENDER_INTERFACE_VULKAN_VERSION;
   core->interface.handle = core;
   core->interface.instance = core->instance;
   core->interface.gpu = core->gpu;
   core->interface.device = core->device;
   core->interface.get_device_proc_addr = core->gdpa;
   core->interface.get_instance_proc_addr = core->gipa;
   core->interface.queue = core->queue;
   core->interface.queue_index = core->core_context.queue_family_index;
   core->interface.set_image = VulkanCore::set_image;
   core->interface.get_sync_index = VulkanCore::get_sync_index;
   core->interface.get_sync_index_mask = VulkanCore::get_sync_index_mask;
   core->interface.set_command_buffers = nullptr;
   core->interface.wait_sync_index = VulkanCore::wait_sync_index;
   core->interface.lock_queue = VulkanCore::lock_queue;
   core->interface.unlock_queue = VulkanCore::unlock_queue;
   core->interface.set_signal_semaphore = nullptr;

   core->core_hw_callback->context_reset();
   return 1;
}

__declspec(dllexport) void *tm3vk_get_interface(void *handle)
{
   VulkanCore *core = static_cast<VulkanCore *>(handle);
   return core ? &core->interface : nullptr;
}

__declspec(dllexport) void tm3vk_begin_frame(void *handle)
{
   VulkanCore *core = static_cast<VulkanCore *>(handle);
   if (!core)
      return;
   core->sync_index = static_cast<unsigned>(core->frame_number++ % kFramesInFlight);
   VulkanCore::wait_sync_index(core);
   core->has_image = false;
}

__declspec(dllexport) int tm3vk_readback(void *handle, uint32_t width, uint32_t height,
      const void **pixels, size_t *pitch, unsigned *pixel_format, char *error, size_t error_cap)
{
   VulkanCore *core = static_cast<VulkanCore *>(handle);
   if (!core || !pixels || !pitch || !pixel_format)
   {
      set_error(error, error_cap, "Argumento invalido al leer el cuadro Vulkan.");
      return 0;
   }
   return core->readback(width, height, pixels, pitch, pixel_format, error, error_cap) ? 1 : 0;
}

__declspec(dllexport) int tm3vk_present(void *handle, uint32_t width, uint32_t height,
      int smooth, int preserve_aspect, char *error, size_t error_cap)
{
   VulkanCore *core = static_cast<VulkanCore *>(handle);
   if (!core)
   {
      set_error(error, error_cap, "Contexto Vulkan inexistente.");
      return 0;
   }
   return core->present(width, height, smooth != 0, preserve_aspect != 0,
         error, error_cap) ? 1 : 0;
}

__declspec(dllexport) int tm3vk_end_frame(void *handle, char *error, size_t error_cap)
{
   VulkanCore *core = static_cast<VulkanCore *>(handle);
   if (!core)
   {
      set_error(error, error_cap, "Contexto Vulkan inexistente.");
      return 0;
   }
   const unsigned slot = core->sync_index % kFramesInFlight;
   std::lock_guard<std::mutex> lock(core->queue_mutex);
   return core->submit_marker(slot, VK_NULL_HANDLE, error, error_cap) ? 1 : 0;
}

__declspec(dllexport) const char *tm3vk_adapter_name(void *handle)
{
   VulkanCore *core = static_cast<VulkanCore *>(handle);
   return core ? core->adapter_name.c_str() : "";
}

__declspec(dllexport) void tm3vk_shutdown_core(void *handle)
{
   VulkanCore *core = static_cast<VulkanCore *>(handle);
   if (!core)
      return;
   if (core->core_hw_callback && core->core_hw_callback->context_destroy && core->device)
      core->core_hw_callback->context_destroy();
   core->destroy();
   delete core;
}

} // extern "C"
