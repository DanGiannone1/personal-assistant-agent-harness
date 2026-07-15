targetScope = 'resourceGroup'

param acrName string
param frontendPrincipalId string
param apiPrincipalId string
param runtimePrincipalId string

var acrPullRoleId = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: acrName
}

resource pullAssignments 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for assignment in [
  { name: 'frontend', principalId: frontendPrincipalId }
  { name: 'api', principalId: apiPrincipalId }
  { name: 'runtime', principalId: runtimePrincipalId }
]: {
  name: guid(acr.id, assignment.name, acrPullRoleId)
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPullRoleId)
    principalId: assignment.principalId
    principalType: 'ServicePrincipal'
  }
}]
