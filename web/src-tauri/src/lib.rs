// 4estDS 瓦客户端外壳(方案A)。
//
// 设计原则:
// - 壳只承载前端 UI, 不内嵌 Python/CUDA/GDAL 等重型依赖。
// - 后端(FastAPI + Worker)作为独立服务部署(内网 GPU 一体机/服务器)。
// - 后端地址由前端构建变量 VITE_API_BASE 注入(见 src-tauri/README.md)。
//
// 如后续需要本地能力(离线瓦片/本地选文件/拉起本机后端), 在此注册 command,
// 并在前端 shared/lib/platform.ts 的防腐缝中调用, 保持 Web/桌面双形态一致。

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .run(tauri::generate_context!())
        .expect("error while running 4estDS desktop shell");
}
