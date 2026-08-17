import { defineMaterial } from "@gdevelop/tsl";
import { mix } from "three/tsl";

export default defineMaterial({
  apiVersion: 1,
  base: "standard",
  label: "Standard PBR",
  parameters: {
    tint: { type: "color", default: "#ff0000" },
    tintAmount: { type: "number", default: 1, min: 0, max: 1 },
    roughness: { type: "number", default: 0.5, min: 0, max: 1 },
    metalness: { type: "number", default: 0, min: 0, max: 1 }
  },
  build({ material, inputs, parameters }) {
    material.colorNode = mix(
      inputs.baseColor,
      parameters.tint,
      parameters.tintAmount
    );
    material.roughnessNode = parameters.roughness;
    material.metalnessNode = parameters.metalness;

  }
});
