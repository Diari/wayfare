// A packing list from the trip length, the weather and the plans.
// Deterministic rules, so the same trip gives the same list.

import { dayNum } from "./itinerary.js";

export const ACTIVITIES = ["business", "beach", "hiking", "skiing", "formal_dinner", "kids", "city"];

const item = (id, label, why, qty) => ({ id, label, ...(qty ? { qty } : {}), ...(why ? { why } : {}) });

export function packingList({ start_date, end_date, activities = [], international = null, weather = null }) {
  const nights = Math.max(0, dayNum(end_date) - dayNum(start_date));
  const acts = new Set((activities || []).filter((a) => ACTIVITIES.includes(a)));
  const w = weather || null;
  const laundry = nights > 7;
  const n = Math.min(nights + 1, 8);

  const docs = [
    item("id", international === false ? "ID card" : "Passport or ID card", international === false ? null : "Check that it is valid for the full trip"),
    item("tickets", "Booking confirmations (offline copy)", "Phone signal can be weak at stations and airports"),
    item("cards", "Bank card and a little local cash"),
    item("insurance", "Travel insurance details"),
  ];
  if (international !== false) docs.push(item("adapter", "Plug adapter", "Check the plug type for the country"));

  const clothes = [
    item("underwear", "Underwear", null, n),
    item("socks", "Socks", null, n),
    item("tops", "Tops / T-shirts", null, Math.min(nights + 1, 6)),
    item("bottoms", "Trousers / skirts", null, Math.min(Math.max(1, Math.ceil((nights + 1) / 3)), 3)),
    item("sleep", "Sleepwear"),
    item("shoes", "Comfortable walking shoes", "You walk more than you expect on trips"),
  ];
  const weatherItems = [];
  if (w) {
    if (w.lo <= 4) {
      weatherItems.push(item("coat", "Warm winter coat", `Lows near ${w.lo}°C`), item("hat", "Warm hat, scarf and gloves"),
        item("thermal", "Thermal layer"));
    } else if (w.lo <= 12) {
      weatherItems.push(item("jacket", "Warm jacket or fleece", `Evenings down to ${w.lo}°C`));
    } else if (w.lo <= 17) {
      weatherItems.push(item("layer", "Light jumper for the evening", `Lows around ${w.lo}°C`));
    }
    if (w.hi >= 25) {
      weatherItems.push(item("sunscreen", "Sunscreen", `Highs up to ${w.hi}°C`), item("sunglasses", "Sunglasses"),
        item("sunhat", "Sun hat"), item("shorts", "Shorts or light clothes"), item("bottle", "Refillable water bottle"));
    }
    if (w.wetDays >= 1) {
      const many = w.wetDays >= Math.max(2, Math.ceil(w.days / 3));
      weatherItems.push(item("umbrella", "Small umbrella", `Rain likely on ${w.wetDays} of ${w.days} days`));
      if (many) weatherItems.push(item("rainjacket", "Waterproof jacket"), item("dryshoes", "Shoes that can get wet"));
    }
    if (w.snow) weatherItems.push(item("boots", "Waterproof boots with grip", "Snow in the weather data"));
  }

  const plans = [];
  if (acts.has("business")) plans.push(item("work-outfit", "Work outfits", null, Math.min(nights + 1, 5)), item("laptop", "Laptop and charger"));
  if (acts.has("formal_dinner")) plans.push(item("smart", "One smart outfit and shoes", "For the dinner reservation"));
  if (acts.has("beach")) plans.push(item("swim", "Swimwear"), item("towel", "Beach towel"), item("flipflops", "Sandals"));
  if (acts.has("hiking")) plans.push(item("hikeshoes", "Hiking shoes"), item("daypack", "Small day backpack"), item("firstaid", "Plasters / small first-aid kit"));
  if (acts.has("skiing")) plans.push(item("skiwear", "Ski jacket and trousers"), item("goggles", "Goggles and ski gloves"), item("lipbalm", "Lip balm with SPF"));
  if (acts.has("kids")) plans.push(item("kids-snacks", "Snacks and a refillable bottle for the children"), item("kids-fun", "Books or games for the journey"), item("kids-meds", "Children's medicines"));

  const care = [
    item("meds", "Your medicines (in hand luggage)"),
    item("toiletries", "Toiletries (liquids under 100 ml for hand luggage)"),
    item("charger", "Phone charger and power bank"),
  ];
  const groups = [
    { group: "Documents and money", items: docs },
    { group: "Clothes", items: clothes },
    ...(weatherItems.length ? [{ group: "For the weather", items: weatherItems }] : []),
    ...(plans.length ? [{ group: "For your plans", items: plans }] : []),
    { group: "Health and devices", items: care },
  ];
  const tips = [];
  if (laundry) tips.push(`The list plans for about a week of clothes. For ${nights} nights, plan to do laundry once.`);
  if (!w) tips.push("No weather data was used. Ask again with the city to add weather items.");
  else if (w.lastYear) tips.push("Weather items use last year's weather on the same dates. Check the forecast a few days before you go.");
  return { nights, groups, tips };
}
