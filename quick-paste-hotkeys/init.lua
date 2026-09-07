-- Quick-paste profile links for job applications
-- Press the hotkey and the URL types itself into whatever field is focused.
-- Add more entries here any time (portfolio, resume link, phone, email, etc).

local profileLinks = {
  { key = "l", label = "LinkedIn", text = "https://linkedin.com/in/adhiraj-sharma7" },
  { key = "g", label = "GitHub",   text = "https://github.com/adiadhiraj07-ops" },
}

for _, link in ipairs(profileLinks) do
  hs.hotkey.bind({"cmd", "ctrl"}, link.key, function()
    hs.eventtap.keyStrokes(link.text)
    hs.alert.show(link.label .. " pasted", 0.6)
  end)
end

hs.alert.show("Hammerspoon config loaded", 1)
